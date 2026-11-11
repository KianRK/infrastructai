"""Download the configured RDD2022 country subsets.

RDD2022 is published on figshare as one 13 GB zip that *stores* (does not compress) one
zip per country. Instead of downloading everything, this module reads the outer zip's
directory with HTTP range requests and fetches only the wanted country archives. Downloads
resume after interruption and are verified against the CRC-32 recorded in the outer zip.

Usage: ``python -m rdd.download [--config configs/data.yaml]``
"""

from __future__ import annotations

import argparse
import io
import logging
import struct
import time
import urllib.error
import urllib.request
import zipfile
import zlib
from collections.abc import Buffer, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from rdd.config import DataConfig

log = logging.getLogger(__name__)

CHUNK = 1 << 20
_LOCAL_HEADER = struct.Struct("<4s22xHH")  # signature, (skipped fields), name len, extra len
COMPLETE_MARKER = ".complete"


class DownloadError(RuntimeError):
    pass


class RangeSource(Protocol):
    """Random access to a remote (or, in tests, local) file."""

    @property
    def size(self) -> int: ...

    def stream(self, start: int, end: int) -> Iterator[bytes]:
        """Yield the bytes in ``[start, end)``."""
        ...


class HttpRangeSource:
    """Range requests against a URL that may redirect to a short-lived signed URL.

    figshare redirects to a pre-signed storage URL that expires, so on failure the
    redirect is resolved again and the transfer continues from the last received byte.
    """

    def __init__(self, url: str, *, retries: int = 8, timeout: float = 60.0) -> None:
        if not url.startswith(("https://", "http://")):
            raise ValueError(f"unsupported URL scheme: {url}")
        self._url = url
        self._retries = retries
        self._timeout = timeout
        self._resolved, self._size = self._resolve()

    @property
    def size(self) -> int:
        return self._size

    def _open(self, url: str, start: int, end: int) -> urllib.response.addinfourl:
        request = urllib.request.Request(  # noqa: S310 - scheme checked in __init__
            url, headers={"Range": f"bytes={start}-{end - 1}", "User-Agent": "roadscan-rdd/0.1"}
        )
        response: urllib.response.addinfourl = urllib.request.urlopen(  # noqa: S310
            request, timeout=self._timeout
        )
        if response.status != 206:
            response.close()
            raise DownloadError(f"server ignored the range request (HTTP {response.status})")
        return response

    def _resolve(self) -> tuple[str, int]:
        with self._open(self._url, 0, 1) as response:
            content_range = response.headers.get("Content-Range", "")
            try:
                size = int(content_range.rsplit("/", 1)[1])
            except (IndexError, ValueError) as exc:
                raise DownloadError(f"unexpected Content-Range: {content_range!r}") from exc
            return response.geturl(), size

    def stream(self, start: int, end: int) -> Iterator[bytes]:
        position = start
        failures = 0
        while position < end:
            try:
                with self._open(self._resolved, position, end) as response:
                    while chunk := response.read(CHUNK):
                        position += len(chunk)
                        failures = 0
                        yield chunk
            except (OSError, DownloadError) as exc:  # URLError and timeouts are OSErrors
                failures += 1
                if failures > self._retries:
                    raise DownloadError(f"giving up at byte {position}: {exc}") from exc
                log.warning("transfer interrupted at byte %d (%s), retrying", position, exc)
                time.sleep(min(2**failures, 30))
                self._resolved, _ = self._resolve()


class _SourceReader(io.RawIOBase):
    """Seekable file object over a RangeSource, so ``zipfile`` can read its directory."""

    def __init__(self, source: RangeSource) -> None:
        self._source = source
        self._pos = 0

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        return self._pos

    def seek(self, offset: int, whence: int = io.SEEK_SET) -> int:
        base = {io.SEEK_SET: 0, io.SEEK_CUR: self._pos, io.SEEK_END: self._source.size}[whence]
        self._pos = base + offset
        return self._pos

    def readinto(self, buffer: Buffer) -> int:
        view = memoryview(buffer).cast("B")
        end = min(self._pos + len(view), self._source.size)
        if end <= self._pos:
            return 0
        data = b"".join(self._source.stream(self._pos, end))
        view[: len(data)] = data
        self._pos += len(data)
        return len(data)


@dataclass(frozen=True)
class StoredMember:
    name: str
    offset: int  # of the member's data within the outer archive
    size: int
    crc32: int


def locate_members(source: RangeSource, names: list[str]) -> list[StoredMember]:
    """Find where the named, uncompressed members live inside the remote zip."""
    with zipfile.ZipFile(io.BufferedReader(_SourceReader(source), CHUNK)) as archive:
        infos = []
        for name in names:
            try:
                infos.append(archive.getinfo(name))
            except KeyError:
                available = ", ".join(archive.namelist())
                raise DownloadError(f"{name} not in archive; it contains: {available}") from None

    members = []
    for info in infos:
        if info.compress_type != zipfile.ZIP_STORED:
            raise DownloadError(f"{info.filename} is compressed; range download not possible")
        header = b"".join(
            source.stream(info.header_offset, info.header_offset + _LOCAL_HEADER.size)
        )
        signature, name_len, extra_len = _LOCAL_HEADER.unpack(header)
        if signature != b"PK\x03\x04":
            raise DownloadError(f"bad local header for {info.filename}")
        offset = info.header_offset + _LOCAL_HEADER.size + name_len + extra_len
        members.append(StoredMember(info.filename, offset, info.file_size, info.CRC))
    return members


def _crc32(path: Path) -> int:
    crc = 0
    with path.open("rb") as fh:
        while chunk := fh.read(CHUNK):
            crc = zlib.crc32(chunk, crc)
    return crc


def fetch_member(source: RangeSource, member: StoredMember, dest: Path) -> None:
    """Download one member to ``dest``, resuming from ``dest.part`` if it exists."""
    part = dest.with_name(dest.name + ".part")
    dest.parent.mkdir(parents=True, exist_ok=True)
    done = part.stat().st_size if part.exists() else 0
    if done > member.size:
        part.unlink()
        done = 0
    if done:
        log.info("resuming %s at %.0f%%", member.name, 100 * done / member.size)

    next_report = time.monotonic() + 15
    with part.open("ab") as fh:
        for chunk in source.stream(member.offset + done, member.offset + member.size):
            fh.write(chunk)
            done += len(chunk)
            if time.monotonic() >= next_report:
                log.info(
                    "%s: %.0f%% of %.1f GB",
                    member.name,
                    100 * done / member.size,
                    member.size / 1e9,
                )
                next_report = time.monotonic() + 15

    if part.stat().st_size != member.size or _crc32(part) != member.crc32:
        part.unlink()
        raise DownloadError(f"{member.name}: checksum mismatch, partial file removed; run again")
    part.replace(dest)


def extract(archive_path: Path, target: Path) -> None:
    with zipfile.ZipFile(archive_path) as archive:
        archive.extractall(target)


def download(cfg: DataConfig, source: RangeSource | None = None) -> None:
    raw = cfg.paths.raw
    todo = [c for c in cfg.countries if not (raw / c / COMPLETE_MARKER).exists()]
    for country in sorted(set(cfg.countries) - set(todo)):
        log.info("%s: already present, skipping", country)
    if not todo:
        return

    source = source or HttpRangeSource(str(cfg.download.url))
    names = [f"{cfg.download.archive_prefix}{country}.zip" for country in todo]
    for country, member in zip(todo, locate_members(source, names), strict=True):
        archive_path = raw / "_archives" / f"{country}.zip"
        if not archive_path.exists():
            log.info("%s: downloading %.2f GB", country, member.size / 1e9)
            fetch_member(source, member, archive_path)
        log.info("%s: extracting", country)
        extract(archive_path, raw)
        if not (raw / country).is_dir():
            raise DownloadError(f"{archive_path} did not contain a {country}/ directory")
        (raw / country / COMPLETE_MARKER).touch()
        if not cfg.download.keep_archives:
            archive_path.unlink()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", type=Path, default=Path("configs/data.yaml"))
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    download(DataConfig.from_yaml(args.config))


if __name__ == "__main__":
    main()
