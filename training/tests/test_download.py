import io
import zipfile
from collections.abc import Iterator
from pathlib import Path

import pytest

from rdd.config import DataConfig
from rdd.download import (
    COMPLETE_MARKER,
    DownloadError,
    download,
    fetch_member,
    locate_members,
)


class BytesSource:
    """In-memory RangeSource that records which byte ranges were requested."""

    def __init__(self, data: bytes) -> None:
        self.data = data
        self.requests: list[tuple[int, int]] = []

    @property
    def size(self) -> int:
        return len(self.data)

    def stream(self, start: int, end: int) -> Iterator[bytes]:
        self.requests.append((start, end))
        for pos in range(start, end, 1000):  # several chunks, like a real transfer
            yield self.data[pos : min(pos + 1000, end)]


def country_zip(country: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(f"{country}/train/images/{country}_0.jpg", b"jpeg-bytes" * 500)
        archive.writestr(f"{country}/train/annotations/xmls/{country}_0.xml", "<annotation/>")
    return buffer.getvalue()


def outer_zip(countries: list[str], compression: int = zipfile.ZIP_STORED) -> bytes:
    """Same shape as the figshare file: a zip that contains one zip per country."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression) as archive:
        for country in countries:
            archive.writestr(f"RDD/{country}.zip", country_zip(country))
    return buffer.getvalue()


def test_download_fetches_only_configured_countries(data_config: DataConfig) -> None:
    source = BytesSource(outer_zip(["Aland", "Borduria", "Syldavia"]))
    download(data_config, source)

    raw = data_config.paths.raw
    assert (raw / "Aland/train/images/Aland_0.jpg").read_bytes() == b"jpeg-bytes" * 500
    assert (raw / "Borduria/train/annotations/xmls/Borduria_0.xml").exists()
    assert not (raw / "Syldavia").exists()
    assert not (raw / "_archives/Aland.zip").exists()  # keep_archives is false


def test_download_skips_countries_that_are_complete(data_config: DataConfig) -> None:
    source = BytesSource(outer_zip(["Aland", "Borduria"]))
    download(data_config, source)
    assert (data_config.paths.raw / "Aland" / COMPLETE_MARKER).exists()

    source.requests.clear()
    download(data_config, source)
    assert source.requests == []


def test_interrupted_download_resumes_where_it_stopped(tmp_path: Path) -> None:
    source = BytesSource(outer_zip(["Aland"]))
    (member,) = locate_members(source, ["RDD/Aland.zip"])
    payload = source.data[member.offset : member.offset + member.size]
    dest = tmp_path / "Aland.zip"
    dest.with_name("Aland.zip.part").write_bytes(payload[:300])

    source.requests.clear()
    fetch_member(source, member, dest)

    assert dest.read_bytes() == payload
    assert source.requests == [(member.offset + 300, member.offset + member.size)]


def test_corrupt_download_is_detected_and_discarded(tmp_path: Path) -> None:
    source = BytesSource(outer_zip(["Aland"]))
    (member,) = locate_members(source, ["RDD/Aland.zip"])
    dest = tmp_path / "Aland.zip"
    part = dest.with_name("Aland.zip.part")
    part.write_bytes(b"\0" * 300)  # wrong bytes left over from an earlier attempt

    with pytest.raises(DownloadError, match="checksum mismatch"):
        fetch_member(source, member, dest)
    assert not dest.exists()
    assert not part.exists()  # so the next run starts clean


def test_unknown_country_lists_what_is_available() -> None:
    source = BytesSource(outer_zip(["Aland"]))
    with pytest.raises(DownloadError, match=r"RDD/Aland\.zip"):
        locate_members(source, ["RDD/Atlantis.zip"])


def test_compressed_outer_member_is_rejected() -> None:
    # Byte ranges of a compressed member are not the member's content.
    source = BytesSource(outer_zip(["Aland"], zipfile.ZIP_DEFLATED))
    with pytest.raises(DownloadError, match="compressed"):
        locate_members(source, ["RDD/Aland.zip"])
