import time
import uuid
import hashlib
import structlog
import logging
import sys
from fastapi import FastAPI, Request, Response
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
import httpx

# ─── Logging Setup ───────────────────────────────────────────────
structlog.configure(
    processors=[
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.JSONRenderer()
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    logger_factory=structlog.stdlib.LoggerFactory(),
)
logging.basicConfig(format="%(message)s", stream=sys.stdout, level=logging.INFO)
logger = structlog.get_logger().bind(service="service_b")

# ─── App ─────────────────────────────────────────────────────────
app = FastAPI(title="Service B - Business Logic")

# ─── Prometheus Metrics ──────────────────────────────────────────
REQUEST_COUNT = Counter(
    "service_b_requests_total",
    "Total requests to Service B",
    ["endpoint", "status"]
)
REQUEST_LATENCY = Histogram(
    "service_b_request_duration_seconds",
    "Request latency for Service B",
    ["endpoint"],
    buckets=[.005, .01, .025, .05, .1, .25, .5, 1.0, 2.5, 5.0]
)
COMPUTE_DURATION = Histogram(
    "service_b_compute_duration_seconds",
    "Internal compute time for Service B"
)

# ─── Middleware ───────────────────────────────────────────────────
@app.middleware("http")
async def observability_middleware(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    duration = time.perf_counter() - start

    REQUEST_LATENCY.labels(endpoint=request.url.path).observe(duration)
    logger.info(
        "request_completed",
        path=request.url.path,
        status_code=response.status_code,
        duration_ms=round(duration * 1000, 2)
    )
    return response

# ─── CPU Work Simulation ─────────────────────────────────────────
def _cpu_work(data: dict) -> str:
    """Simulates real computation — gives CPU stress injection something to amplify"""
    payload_str = str(data)
    result = payload_str
    for _ in range(1000):
        result = hashlib.sha256(result.encode()).hexdigest()
    return result

# ─── Routes ──────────────────────────────────────────────────────
@app.post("/compute")
async def compute(payload: dict):
    request_id = payload.get("request_id", str(uuid.uuid4()))

    # Simulate CPU work
    compute_start = time.perf_counter()
    result = _cpu_work(payload.get("data", {}))
    compute_time = time.perf_counter() - compute_start
    COMPUTE_DURATION.observe(compute_time)

    # Call Service C
    async with httpx.AsyncClient(timeout=5.0) as client:
        try:
            store_resp = await client.post(
                "http://service_c:8002/store",
                json={"request_id": request_id, "result": result}
            )
            REQUEST_COUNT.labels(endpoint="/compute", status=store_resp.status_code).inc()

            logger.info(
                "compute_completed",
                request_id=request_id,
                compute_ms=round(compute_time * 1000, 2),
                store_status=store_resp.status_code
            )
            return {
                "request_id": request_id,
                "result": result,
                "compute_ms": round(compute_time * 1000, 2)
            }

        except httpx.TimeoutException:
            REQUEST_COUNT.labels(endpoint="/compute", status=504).inc()
            logger.error("store_timeout", request_id=request_id)
            return Response(status_code=504, content="Store timeout")

        except httpx.ConnectError:
            REQUEST_COUNT.labels(endpoint="/compute", status=502).inc()
            logger.error("store_unreachable", request_id=request_id)
            return Response(status_code=502, content="Store unavailable")

@app.get("/health")
def health():
    return {"status": "healthy", "service": "service_b"}

@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)