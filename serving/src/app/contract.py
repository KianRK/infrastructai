"""Writes the committed API contract: ``python -m app.contract``."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.schemas import AnalysisResponse

SCHEMA_PATH = Path(__file__).parents[2] / "contract" / "analysis_response.schema.json"


def analysis_response_schema() -> dict[str, Any]:
    return AnalysisResponse.model_json_schema()


if __name__ == "__main__":
    SCHEMA_PATH.write_text(
        json.dumps(analysis_response_schema(), indent=2) + "\n", encoding="utf-8"
    )
    print(f"wrote {SCHEMA_PATH}")
