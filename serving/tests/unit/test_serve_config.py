"""The Serve config files are what actually gets deployed, so they are checked too."""

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError
from ray.serve.schema import ServeDeploySchema

from app.main import build_app

CONFIG_DIR = Path(__file__).parents[2] / "config"
CONFIGS = sorted(CONFIG_DIR.glob("serve.*.yaml"))
APP_DEPLOYMENTS = {"Api", "Detector", "Describer", "Traffic"}


@pytest.mark.parametrize("path", CONFIGS, ids=lambda p: p.name)
def test_config_is_valid_and_builds_the_application(path: Path) -> None:
    config = ServeDeploySchema.model_validate(yaml.safe_load(path.read_text()))
    (application,) = config.applications
    assert application.import_path == "app.main:build_app"

    build_app(application.args)  # exactly what Serve does with the file

    # A misspelt deployment name would be rejected only at deploy time.
    assert {d.name for d in application.deployments} <= APP_DEPLOYMENTS


def test_unknown_argument_is_rejected() -> None:
    with pytest.raises(ValidationError, match="detektor"):
        build_app({"detektor": {"backend": "dummy"}})
