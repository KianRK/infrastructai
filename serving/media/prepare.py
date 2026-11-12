#!/usr/bin/env python3
"""Download the videos of the live-traffic page and convert them for serving.

    python3 serving/media/prepare.py <output directory> [--cache <directory>]

For every entry of streams.json this writes

    <id>.mp4            what the browser plays (H.264, at most 1280 px wide, no audio)
    <id>.analysis.mp4   what the server analyses (640 px wide, 5 frames per second)

and a manifest.json describing them. Downloads are verified against the SHA-256 in
streams.json. Needs ffmpeg and ffprobe; standard library only, because it also runs in
a build stage of the serving image.
"""

from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ANALYSIS_FPS = 5
ANALYSIS_WIDTH = 640
# Wikimedia asks automated clients to identify themselves.
USER_AGENT = "media-prepare-script/1.0"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        while chunk := file.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def download(url: str, expected: str, target: Path, attempts: int = 5) -> None:
    """Fetch ``url`` to ``target`` unless it is already there with the right checksum.

    Large downloads sometimes end early; an incomplete file is continued with a range
    request instead of started again.
    """
    if target.is_file() and sha256(target) == expected:
        return
    if not url.startswith("https://"):
        raise ValueError(f"refusing to download from {url}")
    partial = target.with_suffix(target.suffix + ".part")
    partial.unlink(missing_ok=True)
    for attempt in range(1, attempts + 1):
        have = partial.stat().st_size if partial.exists() else 0
        headers = {"User-Agent": USER_AGENT}
        if have:
            headers["Range"] = f"bytes={have}-"
        print(f"downloading {url} (attempt {attempt}, from byte {have})", flush=True)
        try:
            request = urllib.request.Request(url, headers=headers)  # noqa: S310
            with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310
                # 200 instead of 206: the server ignored the range and sends everything.
                mode = "ab" if have and response.status == 206 else "wb"
                with partial.open(mode) as file:
                    while chunk := response.read(1 << 20):
                        file.write(chunk)
        except urllib.error.HTTPError as error:
            if error.code == 416:  # nothing left to fetch, yet the checksum was wrong
                partial.unlink(missing_ok=True)
            print(f"  HTTP {error.code}", flush=True)
            time.sleep(2 * attempt)
            continue
        except (OSError, http.client.HTTPException) as error:
            print(f"  interrupted: {error}", flush=True)
            time.sleep(2 * attempt)
            continue
        if sha256(partial) == expected:
            partial.rename(target)
            return
        print(f"  incomplete or altered ({partial.stat().st_size} bytes)", flush=True)
        time.sleep(2 * attempt)
    actual = sha256(partial) if partial.exists() else "nothing"
    partial.unlink(missing_ok=True)
    raise RuntimeError(f"checksum mismatch for {url}: expected {expected}, got {actual}")


def run(*command: str) -> str:
    return subprocess.run(command, check=True, capture_output=True, text=True).stdout  # noqa: S603


def convert(source: Path, crop: str | None, display: Path, analysis: Path) -> None:
    cropped = f"crop={crop}," if crop else ""
    print(f"converting {source.name}", flush=True)
    run(
        "ffmpeg", "-v", "error", "-y", "-i", str(source),
        # Browser copy. A key frame every two seconds keeps seeking cheap; faststart puts
        # the index first so playback starts before the download ends.
        "-map", "0:v:0", "-an", "-vf", f"{cropped}scale='min(1280,iw)':-2",
        "-c:v", "libx264", "-preset", "medium", "-crf", "27", "-maxrate", "1600k",
        "-bufsize", "3200k", "-pix_fmt", "yuv420p", "-force_key_frames", "expr:gte(t,n_forced*2)",
        "-movflags", "+faststart", str(display),
        # Analysis copy: one key frame per second, so the server can jump in anywhere.
        "-map", "0:v:0", "-an", "-vf", f"{cropped}fps={ANALYSIS_FPS},scale={ANALYSIS_WIDTH}:-2",
        "-c:v", "libx264", "-preset", "medium", "-crf", "27", "-g", str(ANALYSIS_FPS),
        "-pix_fmt", "yuv420p", str(analysis),
    )  # fmt: skip


def probe(video: Path) -> dict[str, float | int]:
    entries = "stream=width,height:format=duration"
    info = json.loads(
        run(
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            entries,
            "-of",
            "json",
            str(video),
        )
    )
    return {
        "duration": float(info["format"]["duration"]),
        "width": int(info["streams"][0]["width"]),
        "height": int(info["streams"][0]["height"]),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("output", type=Path)
    parser.add_argument("--cache", type=Path, help="where downloads are kept (default: output)")
    args = parser.parse_args()
    output: Path = args.output
    cache: Path = args.cache or output
    output.mkdir(parents=True, exist_ok=True)
    cache.mkdir(parents=True, exist_ok=True)

    manifest = []
    for entry in json.loads((HERE / "streams.json").read_text()):
        stream_id = entry["id"]
        source = cache / f"{stream_id}.source"
        display = output / f"{stream_id}.mp4"
        analysis = output / f"{stream_id}.analysis.mp4"
        download(entry["download_url"], entry["sha256"], source)
        convert(source, entry["crop"], display, analysis)
        public = {
            key: entry[key]
            for key in ("id", "title", "location", "attribution", "licence", "source_url")
        }
        manifest.append(public | probe(display))
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    print(f"wrote {len(manifest)} streams to {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
