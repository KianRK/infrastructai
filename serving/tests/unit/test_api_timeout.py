import asyncio

import pytest
from fastapi import HTTPException

from app.api import within


def test_answer_in_time_is_passed_through() -> None:
    async def answer() -> str:
        return "ok"

    assert asyncio.run(within(answer(), 1.0, "detector")) == "ok"


def test_unavailable_model_becomes_503_instead_of_waiting() -> None:
    async def scenario() -> asyncio.Future[str]:
        never: asyncio.Future[str] = asyncio.get_running_loop().create_future()
        with pytest.raises(HTTPException) as caught:
            await within(never, 0.01, "detector")
        assert caught.value.status_code == 503
        assert caught.value.headers == {"Retry-After": "30"}
        return never

    assert asyncio.run(scenario()).cancelled()
