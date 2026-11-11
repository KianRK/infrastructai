import os
import socket
from collections.abc import Iterator

import httpx
import pytest

# Must be set before `ray` is first imported (Ray reads it at import time). When started
# through `uv run`, Ray otherwise launches its workers with `uv run` too, which resolves a
# different environment (without Ray) from the workers' working directory. Workers must
# simply inherit this interpreter.
os.environ["RAY_ENABLE_UV_RUN_RUNTIME_ENV"] = "0"


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port: int = sock.getsockname()[1]
        return port


@pytest.fixture(scope="session")
def client() -> Iterator[httpx.Client]:
    """The real Serve application (proxy, three deployments) with dummy backends."""
    import ray
    from ray import serve

    from app.main import build_app
    from app.settings import AppArgs

    port = _free_port()
    # Logical CPUs: each of the three deployments reserves one by default, whatever the
    # machine actually has.
    ray.init(num_cpus=4, include_dashboard=False, configure_logging=False)
    try:
        serve.start(http_options={"host": "127.0.0.1", "port": port})
        serve.run(build_app(AppArgs()), name="roadscan", route_prefix="/")
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=30) as http:
            yield http
    finally:
        serve.shutdown()  # type: ignore[no-untyped-call]
        ray.shutdown()
