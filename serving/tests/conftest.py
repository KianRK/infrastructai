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


TEST_PASSWORD = "integration-test-password"
# Replicas inherit the environment of the process that starts Ray.
os.environ["ROADSCAN_DEMO_PASSWORD"] = TEST_PASSWORD
os.environ["ROADSCAN_JWT_SECRET"] = "integration-test-signing-key-0123456789"


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port: int = sock.getsockname()[1]
        return port


@pytest.fixture(scope="session")
def base_url(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    """The real Serve application (proxy, four deployments). Detector and LLM are the
    dummy backends; the traffic deployment reads a generated two-second video and runs a
    tiny ONNX model that always finds one car."""
    import ray
    from ray import serve

    from app.main import build_app
    from app.settings import AppArgs, AuthArgs, OnnxTrafficArgs, RateLimit
    from tests.media import write_media_dir, write_traffic_model

    tmp = tmp_path_factory.mktemp("traffic")
    media = write_media_dir(tmp / "media", seconds=2.0)
    model = write_traffic_model(tmp / "traffic.onnx", [[16, 12, 48, 36, 0.9, 2]])

    port = _free_port()
    # Logical CPUs: each of the four deployments reserves one by default, whatever the
    # machine actually has.
    ray.init(num_cpus=5, include_dashboard=False, configure_logging=False)
    try:
        serve.start(http_options={"host": "127.0.0.1", "port": port})
        args = AppArgs(
            auth=AuthArgs(
                cookie_secure=False,  # the tests talk plain HTTP
                # Tests act as the trusted proxy and give every test its own client
                # address, so their rate-limit budgets do not interfere.
                trusted_proxy_hops=1,
                login_limit=RateLimit(limit=3, window_seconds=300),
                analyze_session_limit=RateLimit(limit=4, window_seconds=300),
                analyze_client_limit=RateLimit(limit=6, window_seconds=300),
            ),
            traffic=OnnxTrafficArgs(
                backend="onnx",
                model_uri=str(model),
                media_dir=media,
                track_min_hits=1,
                track_count_hits=1,
                max_viewers=2,
                connection_seconds=3,
            ),
        )
        serve.run(build_app(args), name="roadscan", route_prefix="/")
        yield f"http://127.0.0.1:{port}"
    finally:
        serve.shutdown()  # type: ignore[no-untyped-call]
        ray.shutdown()


_addresses = (f"198.51.100.{i}" for i in range(1, 255))


@pytest.fixture
def anonymous(base_url: str) -> Iterator[httpx.Client]:
    """A client without a session, coming from an address no other test uses."""
    headers = {"X-Forwarded-For": next(_addresses)}
    with httpx.Client(base_url=base_url, timeout=30, headers=headers) as http:
        yield http


@pytest.fixture
def client(anonymous: httpx.Client) -> httpx.Client:
    """A logged-in client."""
    response = anonymous.post("/api/auth/login", json={"password": TEST_PASSWORD})
    assert response.status_code == 204, response.text
    return anonymous
