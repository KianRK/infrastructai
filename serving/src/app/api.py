"""HTTP API deployment: validates the upload and orchestrates detector and describer.

No ``from __future__ import annotations`` here: with postponed annotations FastAPI did
not recognise the upload parameter of the route method and answered HTTP 422.
"""

from typing import Annotated, Any

from fastapi import FastAPI, File, HTTPException, UploadFile, status
from pydantic import BaseModel
from ray import serve
from ray.serve.handle import DeploymentHandle

from app.detector import DetectorOutput
from app.imaging import InvalidImageError, decode_image
from app.llm import DescriberOutput
from app.schemas import AnalysisResponse
from app.settings import AppArgs


class ErrorResponse(BaseModel):
    detail: str


class HealthResponse(BaseModel):
    status: str


fastapi_app = FastAPI(
    title="RoadScan API",
    version="0.1.0",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
    redoc_url=None,
)


@serve.deployment
@serve.ingress(fastapi_app)
class Api:
    def __init__(
        self, args: AppArgs, detector: DeploymentHandle[Any], describer: DeploymentHandle[Any]
    ) -> None:
        self._args = args
        self._detector = detector
        self._describer = describer

    @fastapi_app.get("/api/healthz")
    async def healthz(self) -> HealthResponse:
        return HealthResponse(status="ok")

    @fastapi_app.post(
        "/api/analyze",
        responses={status.HTTP_400_BAD_REQUEST: {"model": ErrorResponse}},
    )
    async def analyze(self, file: Annotated[UploadFile, File()]) -> AnalysisResponse:
        try:
            image = decode_image(await file.read(), self._args.max_image_pixels)
        except InvalidImageError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

        detected: DetectorOutput = await self._detector.detect.remote(image)
        described: DescriberOutput = await self._describer.describe.remote(detected.detections)
        height, width = image.shape[:2]
        return AnalysisResponse(
            detections=detected.detections,
            description=described.description,
            description_source=described.source,
            image_width=width,
            image_height=height,
            detector_version=detected.version,
            llm_model=described.model,
        )
