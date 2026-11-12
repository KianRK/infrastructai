"""Ray Serve application builder: ``import_path: app.main:build_app``."""

from __future__ import annotations

from typing import Any

from ray.serve import Application, Deployment

from app.api import Api
from app.detector import Detector
from app.llm import Describer
from app.settings import AppArgs
from app.traffic.deployment import Traffic


def _bind(deployment: object, *args: object) -> Application:
    # ``@serve.deployment`` turns the class into a Deployment, which type checkers
    # cannot see; this keeps the call sites typed.
    if not isinstance(deployment, Deployment):
        raise TypeError(f"{deployment!r} is not a Serve deployment")
    return deployment.bind(*args)


def build_app(args: AppArgs | dict[str, Any]) -> Application:
    """Four deployments, composed through deployment handles.

    Serve passes the ``args:`` section of its config file as a plain dict; it is
    validated here so a typo in the config fails the deployment with a clear error.

    Replica counts and resources are not set here; they come from the ``deployments:``
    section of the Serve config so each environment can size them differently.
    """
    args = AppArgs.model_validate(args)
    detector = _bind(Detector, args.detector)
    describer = _bind(Describer, args.llm)
    traffic = _bind(Traffic, args.traffic)
    return _bind(Api, args, detector, describer, traffic)
