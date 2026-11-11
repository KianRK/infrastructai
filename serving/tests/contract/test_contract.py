"""The API contract is a committed JSON Schema; the frontend types are written against it.

If this test fails, the response schema changed. When that is intended, regenerate the
file with ``uv run python -m app.contract`` and update ``frontend/src/api/types.ts``.
"""

import json

from app.api import fastapi_app
from app.contract import SCHEMA_PATH, analysis_response_schema


def test_response_schema_matches_committed_contract() -> None:
    committed = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert analysis_response_schema() == committed


def test_openapi_declares_the_contract_for_the_analyze_endpoint() -> None:
    operation = fastapi_app.openapi()["paths"]["/api/analyze"]["post"]
    ok_schema = operation["responses"]["200"]["content"]["application/json"]["schema"]
    assert ok_schema == {"$ref": "#/components/schemas/AnalysisResponse"}
    assert "400" in operation["responses"]
