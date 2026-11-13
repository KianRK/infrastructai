"""Application metrics.

Ray collects them from every replica and exports them next to its own on the node's
metrics port; in Prometheus each name carries the prefix ``ray_``. Request counts and
latencies per route and per deployment are not repeated here: Ray Serve already reports
them (``ray_serve_num_http_requests_total``, ``ray_serve_http_request_latency_ms``,
``ray_serve_deployment_processing_latency_ms``).

Tag values are fixed, small sets (damage class, stream id, reason); nothing that comes
from a request, such as a client address, is used as a tag.
"""

from ray.util.metrics import Counter, Gauge, Histogram

# Model calls take between 20 ms (traffic frame) and more than a minute (language model
# under load), so the buckets are spread over that range.
_SECONDS = [0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 20.0, 40.0, 80.0]

DETECTOR_SECONDS = Histogram(
    "roadscan_detector_inference_seconds",
    description="Time the damage detector needs for one image, preprocessing included.",
    boundaries=_SECONDS,
)
DETECTIONS = Counter(
    "roadscan_detections_total",
    description="Detected damage, by class.",
    tag_keys=("damage_class",),
)
DESCRIPTION_SECONDS = Histogram(
    "roadscan_description_seconds",
    description="Time to produce the summary, by its source (llm, template, no_damage).",
    boundaries=_SECONDS,
    tag_keys=("source",),
)
LOGINS = Counter(
    "roadscan_logins_total",
    description="Login attempts, by result (ok, wrong_password).",
    tag_keys=("result",),
)
REJECTED = Counter(
    "roadscan_rejected_requests_total",
    description="Requests refused by the application, by reason "
    "(login_limit, client_limit, session_limit, invalid_upload, model_timeout).",
    tag_keys=("reason",),
)
TRAFFIC_VIEWERS = Gauge(
    "roadscan_traffic_viewers",
    description="Open event streams of the live-traffic page on this API replica.",
)
TRAFFIC_FRAMES = Counter(
    "roadscan_traffic_frames_total",
    description="Video frames of the live-traffic analysis, by stream and result "
    "(analysed, dropped: the analysis was too far behind the clock).",
    tag_keys=("stream", "result"),
)
TRAFFIC_SECONDS = Histogram(
    "roadscan_traffic_inference_seconds",
    description="Time the traffic detector needs for one frame, by stream.",
    boundaries=_SECONDS,
    tag_keys=("stream",),
)
