import time
import uuid
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
logger = structlog.get_logger().bind(service="service_a")

# ─── App ─────────────────────────────────────────────────────────
app = FastAPI(title="Service A - API Gateway")

# ─── Prometheus Metrics ──────────────────────────────────────────
REQUEST_COUNT = Counter(
    "service_a_requests_total",
    "Total requests to Service A",
    ["method", "endpoint", "status"]
)
REQUEST_LATENCY = Histogram(
    "service_a_request_duration_seconds",
    "Request latency for Service A",
    ["endpoint"],
    buckets=[.005, .01, .025, .05, .1, .25, .5, 1.0, 2.5, 5.0]
)

# ─── Middleware ───────────────────────────────────────────────────
@app.middleware("http")
async def observability_middleware(request: Request, call_next):
    start = time.perf_counter()
    request_id = str(uuid.uuid4())

    response = await call_next(request)
    duration = time.perf_counter() - start

    REQUEST_COUNT.labels(
        method=request.method,
        endpoint=request.url.path,
        status=response.status_code
    ).inc()
    REQUEST_LATENCY.labels(endpoint=request.url.path).observe(duration)

    logger.info(
        "request_completed",
        request_id=request_id,
        method=request.method,
        path=request.url.path,
        status_code=response.status_code,
        duration_ms=round(duration * 1000, 2)
    )
    return response

# ─── Routes ──────────────────────────────────────────────────────
@app.post("/process")
async def process(payload: dict):
    request_id = str(uuid.uuid4())

    async with httpx.AsyncClient(timeout=5.0) as client:
        try:
            start = time.perf_counter()
            resp = await client.post(
                "http://service_b:8001/compute",
                json={"request_id": request_id, "data": payload}
            )
            downstream_latency = time.perf_counter() - start

            logger.info(
                "downstream_call_success",
                request_id=request_id,
                target="service_b",
                downstream_latency_ms=round(downstream_latency * 1000, 2)
            )
            return {
                "status": "ok",
                "request_id": request_id,
                "result": resp.json(),
                "downstream_latency_ms": round(downstream_latency * 1000, 2)
            }

        except httpx.TimeoutException:
            logger.error("downstream_timeout", request_id=request_id, target="service_b")
            return Response(status_code=504, content="Gateway timeout")

        except httpx.ConnectError:
            logger.error("downstream_unreachable", request_id=request_id, target="service_b")
            return Response(status_code=502, content="Service unavailable")

@app.get("/health")
def health():
    return {"status": "healthy", "service": "service_a"}

@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)