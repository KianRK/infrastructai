#!/usr/bin/env python3
"""End-to-end check of a running RoadScan stack: frontend, login, analysis, live traffic,
logout.

    ROADSCAN_DEMO_PASSWORD=... python3 scripts/smoke_test.py https://<host>

Standard library only, so it runs on a bare CI runner. Uses two login attempts and one
analysis, well inside the rate limits. Exits non-zero on the first failed check.
"""

from __future__ import annotations

import argparse
import http.cookiejar
import json
import os
import struct
import sys
import urllib.error
import urllib.request
import zlib

REQUIRED_FIELDS = {
    "detections",
    "description",
    "recommendations",
    "disclaimer",
    "description_source",
    "image_width",
    "image_height",
    "detector_version",
    "llm_model",
}


def grey_png(side: int = 64) -> bytes:
    """A valid plain grey PNG, built by hand to avoid an imaging dependency."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    header = struct.pack(">IIBBBBB", side, side, 8, 2, 0, 0, 0)  # 8-bit RGB
    rows = (b"\x00" + b"\x80" * (side * 3)) * side
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )


class Client:
    def __init__(self, base_url: str, timeout: float) -> None:
        self._base = base_url.rstrip("/")
        self._timeout = timeout
        self._opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
        )

    def request(
        self, method: str, path: str, body: bytes | None = None, content_type: str | None = None
    ) -> tuple[int, bytes]:
        request = urllib.request.Request(self._base + path, data=body, method=method)  # noqa: S310
        if content_type:
            request.add_header("Content-Type", content_type)
        try:
            with self._opener.open(request, timeout=self._timeout) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as error:
            return error.code, error.read()
        except OSError as error:  # unreachable, timeout, TLS failure
            print(f"FAIL  {method} {path}: {error}")
            sys.exit(1)

    def login(self, password: str) -> int:
        body = json.dumps({"password": password}).encode()
        return self.request("POST", "/api/auth/login", body, "application/json")[0]

    def first_event(self, path: str) -> dict[str, object] | None:
        """The first message of a server-sent event stream, or None if there is none."""
        request = urllib.request.Request(self._base + path)  # noqa: S310
        try:
            with self._opener.open(request, timeout=self._timeout) as response:
                for _ in range(200):  # the stream starts with a retry hint and keep-alives
                    line = response.readline()
                    if not line:
                        break
                    if line.startswith(b"data: "):
                        event: dict[str, object] = json.loads(line[6:])
                        return event
        except (OSError, ValueError) as error:
            print(f"FAIL  GET {path}: {error}")
            sys.exit(1)
        return None

    def analyze(self, image: bytes) -> tuple[int, bytes]:
        boundary = "roadscan-smoke-test"
        body = (
            (
                f"--{boundary}\r\n"
                'Content-Disposition: form-data; name="file"; filename="smoke.png"\r\n'
                "Content-Type: image/png\r\n\r\n"
            ).encode()
            + image
            + f"\r\n--{boundary}--\r\n".encode()
        )
        return self.request(
            "POST", "/api/analyze", body, f"multipart/form-data; boundary={boundary}"
        )


def expect(what: str, actual: object, expected: object) -> None:
    if actual != expected:
        print(f"FAIL  {what}: expected {expected!r}, got {actual!r}")
        sys.exit(1)
    print(f"ok    {what}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("base_url", help="e.g. http://localhost:8080")
    parser.add_argument("--timeout", type=float, default=180.0, help="seconds per request")
    args = parser.parse_args()
    if not args.base_url.startswith(("http://", "https://")):
        parser.error("base_url must start with http:// or https://")
    password = os.environ.get("ROADSCAN_DEMO_PASSWORD")
    if not password:
        parser.error("set ROADSCAN_DEMO_PASSWORD")

    client = Client(args.base_url, args.timeout)

    status, page = client.request("GET", "/")
    expect("frontend is served", (status, b"<title>RoadScan</title>" in page), (200, True))
    expect("API is healthy", client.request("GET", "/api/healthz")[0], 200)
    expect("analysis without login is refused", client.analyze(grey_png())[0], 401)
    expect("wrong password is refused", client.login(password + "-wrong"), 401)
    expect("login succeeds", client.login(password), 204)

    status, raw = client.analyze(grey_png())
    expect("analysis succeeds", status, 200)
    result = json.loads(raw)
    expect("response has the agreed fields", REQUIRED_FIELDS - result.keys(), set())
    # A plain grey image shows no road damage; anything else means the model is broken.
    expect("no damage is reported for a blank image", result["detections"], [])
    expect("the no-damage text is used", result["description_source"], "no_damage")

    # Live traffic: the streams are listed and the analysis produces results for them.
    status, raw = client.request("GET", "/api/traffic/streams")
    expect("traffic streams are listed", status, 200)
    streams = {stream["id"] for stream in json.loads(raw)["streams"]}
    expect("there is at least one traffic stream", bool(streams), True)
    event = client.first_event("/api/traffic/events")
    expect("the traffic analysis sends results", event is not None, True)
    if event is not None:
        expect("the result belongs to a listed stream", event.get("stream") in streams, True)
        expect("the result carries statistics", "stats" in event and "objects" in event, True)

    expect("logout succeeds", client.request("POST", "/api/auth/logout")[0], 204)
    expect("session is gone after logout", client.request("GET", "/api/auth/session")[0], 401)
    expect("traffic needs a session", client.request("GET", "/api/traffic/streams")[0], 401)
    print("smoke test passed")


if __name__ == "__main__":
    main()
