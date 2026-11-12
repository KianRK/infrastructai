"""HTTP API deployment: authentication, rate limiting, upload validation, orchestration.

No ``from __future__ import annotations`` here: with postponed annotations FastAPI did
not recognise the upload parameter of the route method and answered HTTP 422.
"""

import asyncio
import logging
import math
from collections.abc import Awaitable
from typing import Annotated, Any

from fastapi import FastAPI, File, HTTPException, Request, Response, UploadFile, status
from pydantic import BaseModel, Field
from ray import serve
from ray.serve.handle import DeploymentHandle

from app.auth import (
    COOKIE_NAME,
    COOKIE_PATH,
    Authenticator,
    InvalidSessionError,
    Session,
    client_address,
)
from app.detector import DetectorOutput
from app.imaging import FileTooLargeError, UploadError, decode_upload
from app.llm import DescriberOutput
from app.ratelimit import Decision, SlidingWindowLimiter
from app.schemas import AnalysisResponse
from app.settings import AppArgs

log = logging.getLogger("ray.serve")


class ErrorResponse(BaseModel):
    detail: str


class HealthResponse(BaseModel):
    status: str


class LoginRequest(BaseModel):
    password: str = Field(min_length=1, max_length=256)


class SessionResponse(BaseModel):
    authenticated: bool
    expires_at: int = Field(description="Unix time at which the session ends.")


_ERRORS: dict[int | str, dict[str, Any]] = {
    code: {"model": ErrorResponse}
    for code in (
        status.HTTP_400_BAD_REQUEST,
        status.HTTP_401_UNAUTHORIZED,
        status.HTTP_413_CONTENT_TOO_LARGE,
        status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
        status.HTTP_429_TOO_MANY_REQUESTS,
        status.HTTP_503_SERVICE_UNAVAILABLE,
    )
}

fastapi_app = FastAPI(
    title="RoadScan API",
    version="0.1.0",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
    redoc_url=None,
)


def _enforce(decision: Decision) -> None:
    if not decision.allowed:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "too many requests",
            headers={"Retry-After": str(max(1, math.ceil(decision.retry_after)))},
        )


async def within[T](call: Awaitable[T], seconds: float, what: str) -> T:
    """Await a model call, answering 503 if it takes longer than ``seconds``.

    A model deployment without a running replica (still loading, or failing to start)
    queues requests indefinitely; the caller should get an answer instead.
    """
    try:
        return await asyncio.wait_for(call, seconds)
    except TimeoutError:
        log.error("%s did not answer within %.0f s", what, seconds)
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            f"{what} is not available",
            headers={"Retry-After": "30"},
        ) from None


@serve.deployment
@serve.ingress(fastapi_app)
class Api:
    def __init__(
        self, args: AppArgs, detector: DeploymentHandle[Any], describer: DeploymentHandle[Any]
    ) -> None:
        self._args = args
        self._detector = detector
        self._describer = describer
        # Raises if a secret is missing: the replica then fails to start, which is the
        # intended outcome (never run without authentication).
        self._auth = Authenticator.from_args(args.auth)
        self._login_limit = SlidingWindowLimiter(args.auth.login_limit)
        self._session_limit = SlidingWindowLimiter(args.auth.analyze_session_limit)
        self._client_limit = SlidingWindowLimiter(args.auth.analyze_client_limit)

    def _client(self, request: Request) -> str:
        return client_address(
            request.client.host if request.client else None,
            request.headers.get("x-forwarded-for"),
            self._args.auth.trusted_proxy_hops,
        )

    def _require_session(self, request: Request) -> Session:
        try:
            return self._auth.verify(request.cookies.get(COOKIE_NAME))
        except InvalidSessionError as exc:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "not logged in") from exc

    @fastapi_app.get("/api/healthz")
    async def healthz(self) -> HealthResponse:
        return HealthResponse(status="ok")

    @fastapi_app.post("/api/auth/login", status_code=status.HTTP_204_NO_CONTENT, responses=_ERRORS)
    async def login(self, body: LoginRequest, request: Request, response: Response) -> None:
        # Every attempt counts, successful or not, so guessing is slowed down regardless
        # of what the attacker learns from the answers.
        _enforce(self._login_limit.hit(self._client(request)))
        if not self._auth.check_password(body.password):
            log.warning("failed login from %s", self._client(request))
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "wrong password")
        token, _ = self._auth.issue()
        response.set_cookie(
            COOKIE_NAME,
            token,
            max_age=self._auth.session_seconds,
            path=COOKIE_PATH,
            httponly=True,  # not readable by JavaScript
            secure=self._args.auth.cookie_secure,
            samesite="strict",  # not sent on cross-site requests: CSRF protection
        )

    @fastapi_app.get("/api/auth/session", responses=_ERRORS)
    async def session(self, request: Request) -> SessionResponse:
        current = self._require_session(request)
        return SessionResponse(authenticated=True, expires_at=current.expires_at)

    @fastapi_app.post("/api/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
    async def logout(self, response: Response) -> None:
        response.delete_cookie(
            COOKIE_NAME,
            path=COOKIE_PATH,
            httponly=True,
            secure=self._args.auth.cookie_secure,
            samesite="strict",
        )

    @fastapi_app.post("/api/analyze", responses=_ERRORS)
    async def analyze(
        self, request: Request, file: Annotated[UploadFile, File()]
    ) -> AnalysisResponse:
        current = self._require_session(request)
        _enforce(self._client_limit.hit(self._client(request)))
        _enforce(self._session_limit.hit(current.id))

        limits = self._args.upload
        try:
            if file.size is not None and file.size > limits.max_bytes:
                raise FileTooLargeError(
                    f"file is larger than {limits.max_bytes // (1024 * 1024)} MB"
                )
            # Read one byte more than allowed, so an oversized upload is detected
            # without holding all of it.
            image = decode_upload(await file.read(limits.max_bytes + 1), limits)
        except UploadError as exc:
            raise HTTPException(exc.status, str(exc)) from exc

        detected: DetectorOutput = await within(
            self._detector.detect.remote(image.pixels),
            self._args.detector_timeout_seconds,
            "detector",
        )
        described: DescriberOutput = await within(
            self._describer.describe.remote(detected.detections),
            self._args.describer_timeout_seconds,
            "language model",
        )
        return AnalysisResponse(
            detections=detected.detections,
            description=described.description,
            description_source=described.source,
            image_width=image.width,
            image_height=image.height,
            detector_version=detected.version,
            llm_model=described.model,
        )
