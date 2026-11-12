from pathlib import Path

import jwt
import pytest

from app.auth import Authenticator, InvalidSessionError, SecretsError, client_address
from app.settings import AuthArgs

SECRET = "s" * 40
OTHER_SECRET = "o" * 40


class Clock:
    def __init__(self, now: float = 1_800_000_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def make(clock: Clock | None = None, secret: str = SECRET) -> Authenticator:
    return Authenticator("correct horse", secret, session_seconds=3600, clock=clock or Clock())


def test_password_check() -> None:
    auth = make()
    assert auth.check_password("correct horse")
    assert not auth.check_password("correct hors")
    assert not auth.check_password("")
    assert not auth.check_password("correct horse ")
    assert not auth.check_password("pässword")  # non-ASCII input must not raise


def test_issued_token_verifies_until_it_expires() -> None:
    clock = Clock()
    auth = make(clock)
    token, session = auth.issue()

    assert auth.verify(token) == session
    assert session.expires_at == int(clock.now) + 3600

    clock.now += 3599
    auth.verify(token)
    clock.now += 1
    with pytest.raises(InvalidSessionError, match="expired"):
        auth.verify(token)


def test_each_login_gets_its_own_session_id() -> None:
    auth = make()
    assert auth.issue()[1].id != auth.issue()[1].id


@pytest.mark.parametrize("token", [None, "", "not-a-jwt", "a.b.c"])
def test_missing_or_malformed_token_is_rejected(token: str | None) -> None:
    with pytest.raises(InvalidSessionError):
        make().verify(token)


def test_token_signed_with_another_key_is_rejected() -> None:
    token, _ = make(secret=OTHER_SECRET).issue()
    with pytest.raises(InvalidSessionError):
        make().verify(token)


def test_unsigned_token_is_rejected() -> None:
    # The classic "alg: none" forgery.
    forged = jwt.encode({"sub": "x", "iat": 1, "exp": 9_999_999_999}, key="", algorithm="none")
    with pytest.raises(InvalidSessionError):
        make().verify(forged)


def test_token_without_expiry_is_rejected() -> None:
    token = jwt.encode({"sub": "x", "iat": 1}, SECRET, algorithm="HS256")
    with pytest.raises(InvalidSessionError):
        make().verify(token)


def test_short_signing_key_is_refused() -> None:
    with pytest.raises(SecretsError, match="at least 32 bytes"):
        make(secret="too-short")


def test_secrets_are_read_from_mounted_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ROADSCAN_DEMO_PASSWORD", "from-env")
    (tmp_path / "demo-password").write_text("from-file\n")  # trailing newline is common
    (tmp_path / "jwt-secret").write_text(SECRET)

    auth = Authenticator.from_args(AuthArgs(secrets_dir=tmp_path))

    assert auth.check_password("from-file")  # the mounted file wins over the environment
    assert not auth.check_password("from-env")


def test_secrets_fall_back_to_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ROADSCAN_DEMO_PASSWORD", "from-env")
    monkeypatch.setenv("ROADSCAN_JWT_SECRET", SECRET)
    assert Authenticator.from_args(AuthArgs()).check_password("from-env")


def test_missing_secret_prevents_startup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ROADSCAN_DEMO_PASSWORD", raising=False)
    monkeypatch.setenv("ROADSCAN_JWT_SECRET", SECRET)
    with pytest.raises(SecretsError, match="ROADSCAN_DEMO_PASSWORD"):
        Authenticator.from_args(AuthArgs(secrets_dir=tmp_path))


@pytest.mark.parametrize(
    ("peer", "forwarded", "hops", "expected"),
    [
        ("10.0.0.5", None, 0, "10.0.0.5"),
        # Header ignored without trusted proxies: a client could put anything there.
        ("10.0.0.5", "1.2.3.4", 0, "10.0.0.5"),
        ("10.0.0.5", "203.0.113.9", 1, "203.0.113.9"),
        # Client-supplied entries come first; only the one our proxy appended counts.
        ("10.0.0.5", "6.6.6.6, 203.0.113.9", 1, "203.0.113.9"),
        ("10.0.0.5", "6.6.6.6, 203.0.113.9, 10.0.0.1", 2, "203.0.113.9"),
        ("10.0.0.5", "203.0.113.9", 2, "10.0.0.5"),  # fewer entries than proxies: fall back
        ("10.0.0.5", "", 1, "10.0.0.5"),
        (None, None, 0, "unknown"),
    ],
)
def test_client_address(peer: str | None, forwarded: str | None, hops: int, expected: str) -> None:
    assert client_address(peer, forwarded, hops) == expected
