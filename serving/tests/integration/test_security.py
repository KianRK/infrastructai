"""Authentication and rate limiting through the real Serve application."""

import io

import httpx
from PIL import Image

from tests.conftest import TEST_PASSWORD


def png() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (32, 32), "gray").save(buffer, "PNG")
    return buffer.getvalue()


def analyze(client: httpx.Client) -> httpx.Response:
    return client.post("/api/analyze", files={"file": ("road.png", png())})


def login(client: httpx.Client, password: str = TEST_PASSWORD) -> httpx.Response:
    return client.post("/api/auth/login", json={"password": password})


def test_health_needs_no_session(anonymous: httpx.Client) -> None:
    assert anonymous.get("/api/healthz").status_code == 200


def test_protected_endpoints_reject_requests_without_a_session(anonymous: httpx.Client) -> None:
    assert analyze(anonymous).status_code == 401
    assert anonymous.get("/api/auth/session").status_code == 401


def test_forged_session_cookie_is_rejected(anonymous: httpx.Client) -> None:
    anonymous.cookies.set("roadscan_session", "eyJhbGciOiJub25lIn0.eyJzdWIiOiJ4In0.", path="/api")
    assert analyze(anonymous).status_code == 401


def test_wrong_password_sets_no_cookie(anonymous: httpx.Client) -> None:
    response = login(anonymous, "wrong")
    assert response.status_code == 401
    assert "set-cookie" not in response.headers


def test_login_sets_a_hardened_cookie_that_grants_access(anonymous: httpx.Client) -> None:
    response = login(anonymous)

    assert response.status_code == 204
    cookie = response.headers["set-cookie"]
    assert cookie.startswith("roadscan_session=")
    attributes = {part.strip().lower() for part in cookie.split(";")[1:]}
    assert {"httponly", "samesite=strict", "path=/api", "max-age=3600"} <= attributes
    assert TEST_PASSWORD not in cookie

    session = anonymous.get("/api/auth/session")
    assert session.status_code == 200
    assert session.json()["authenticated"] is True
    assert analyze(anonymous).status_code == 200


def test_logout_removes_the_session_from_the_browser(client: httpx.Client) -> None:
    response = client.post("/api/auth/logout")
    assert response.status_code == 204
    assert "max-age=0" in response.headers["set-cookie"].lower()
    assert client.get("/api/auth/session").status_code == 401


def test_login_attempts_are_limited_per_client_address(anonymous: httpx.Client) -> None:
    # The test app allows 3 attempts per window.
    assert [login(anonymous, "guess").status_code for _ in range(3)] == [401, 401, 401]

    blocked = login(anonymous)  # even the right password is refused now
    assert blocked.status_code == 429
    assert 1 <= int(blocked.headers["retry-after"]) <= 300


def test_client_cannot_dodge_the_limit_by_spoofing_forwarded_for(
    anonymous: httpx.Client,
) -> None:
    # Our proxy appends the real address last; whatever the client prepends is ignored.
    real = anonymous.headers["X-Forwarded-For"]
    codes = [
        anonymous.post(
            "/api/auth/login",
            json={"password": "guess"},
            headers={"X-Forwarded-For": f"10.9.8.{i}, {real}"},
        ).status_code
        for i in range(4)
    ]
    assert codes == [401, 401, 401, 429]


def test_analysis_is_limited_per_session(client: httpx.Client) -> None:
    # 4 per session in the test app.
    assert [analyze(client).status_code for _ in range(5)] == [200, 200, 200, 200, 429]


def test_new_sessions_do_not_reset_the_per_client_limit(anonymous: httpx.Client) -> None:
    # 6 per client address in the test app, 3 logins allowed: two sessions, 3 requests each.
    codes = []
    for _ in range(2):
        assert login(anonymous).status_code == 204
        codes += [analyze(anonymous).status_code for _ in range(3)]
    assert codes == [200] * 6

    assert login(anonymous).status_code == 204  # a fresh session...
    limited = analyze(anonymous)
    assert limited.status_code == 429  # ...is still the same client
    assert "retry-after" in limited.headers


def test_rejected_upload_never_reaches_the_models(client: httpx.Client) -> None:
    response = client.post("/api/analyze", files={"file": ("x.png", b"GIF89a" + bytes(32))})
    assert response.status_code == 415
