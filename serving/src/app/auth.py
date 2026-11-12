"""Password login and stateless session tokens (JWT in an HttpOnly cookie)."""

from __future__ import annotations

import hmac
import os
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import jwt

from app.settings import AuthArgs

COOKIE_NAME = "roadscan_session"
COOKIE_PATH = "/api"
_ALGORITHM = "HS256"
_MIN_JWT_SECRET_BYTES = 32  # RFC 7518: HS256 keys must be at least 256 bits


class SecretsError(RuntimeError):
    """A required secret is missing or unusable; the deployment must not start."""


class InvalidSessionError(Exception):
    pass


@dataclass(frozen=True)
class Session:
    id: str  # random per login; the key for per-session rate limiting
    expires_at: int  # Unix time


def _read_secret(directory: Path | None, filename: str, env_var: str) -> str:
    if directory is not None and (directory / filename).is_file():
        value = (directory / filename).read_text(encoding="utf-8").strip()
        source = str(directory / filename)
    else:
        value = os.environ.get(env_var, "").strip()
        source = f"${env_var}"
    if not value:
        where = f"{directory / filename} or " if directory is not None else ""
        raise SecretsError(f"secret not found: set {where}${env_var}")
    if "\n" in value:
        raise SecretsError(f"{source} must contain a single line")
    return value


class Authenticator:
    def __init__(
        self,
        password: str,
        jwt_secret: str,
        session_seconds: int,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if len(jwt_secret.encode()) < _MIN_JWT_SECRET_BYTES:
            raise SecretsError(f"JWT secret must be at least {_MIN_JWT_SECRET_BYTES} bytes long")
        self._password = password.encode()
        self._jwt_secret = jwt_secret
        self._session_seconds = session_seconds
        self._clock = clock

    @classmethod
    def from_args(cls, args: AuthArgs) -> Authenticator:
        return cls(
            password=_read_secret(args.secrets_dir, "demo-password", "ROADSCAN_DEMO_PASSWORD"),
            jwt_secret=_read_secret(args.secrets_dir, "jwt-secret", "ROADSCAN_JWT_SECRET"),
            session_seconds=args.session_minutes * 60,
        )

    @property
    def session_seconds(self) -> int:
        return self._session_seconds

    def check_password(self, candidate: str) -> bool:
        # Constant-time comparison: response time must not reveal how many leading
        # characters were right.
        return hmac.compare_digest(candidate.encode(), self._password)

    def issue(self) -> tuple[str, Session]:
        now = int(self._clock())
        session = Session(id=secrets.token_urlsafe(16), expires_at=now + self._session_seconds)
        token = jwt.encode(
            {"sub": session.id, "iat": now, "exp": session.expires_at},
            self._jwt_secret,
            algorithm=_ALGORITHM,
        )
        return token, session

    def verify(self, token: str | None) -> Session:
        if not token:
            raise InvalidSessionError("no session")
        try:
            claims = jwt.decode(
                token,
                self._jwt_secret,
                algorithms=[_ALGORITHM],  # never trust the algorithm named in the token
                options={
                    "require": ["sub", "exp", "iat"],
                    "verify_exp": False,
                    "verify_iat": False,
                },
            )
        except jwt.InvalidTokenError as exc:
            raise InvalidSessionError("invalid session token") from exc
        # Expiry is checked against the injected clock (PyJWT would use the system clock);
        # the signature and the presence of the claims are still verified above.
        if int(claims["exp"]) <= self._clock():
            raise InvalidSessionError("session expired")
        return Session(id=str(claims["sub"]), expires_at=int(claims["exp"]))


def client_address(peer: str | None, forwarded_for: str | None, trusted_hops: int) -> str:
    """The client address to rate-limit on.

    X-Forwarded-For is client-controlled except for the entries appended by our own
    proxies, so only the entry added by the outermost trusted proxy is used: with N
    trusted hops, the N-th value from the right. Without trusted proxies the header is
    ignored entirely.
    """
    if trusted_hops > 0 and forwarded_for:
        entries = [entry.strip() for entry in forwarded_for.split(",") if entry.strip()]
        if len(entries) >= trusted_hops:
            return entries[-trusted_hops]
    return peer or "unknown"
