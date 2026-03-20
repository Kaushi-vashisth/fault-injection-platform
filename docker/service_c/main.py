import time
import uuid
import structlog
import logging
import sys
from fastapi import FastAPI, Request, Response
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure, ServerSelectionTimeoutError

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
logger = structlog.get_logger().bind(service="service_c")

# ─── App ─────────────────────────────────────────────────────────
app = FastAPI(title="Service C - Data Layer")

# ─── MongoDB Connection ───────────────────────────────────────────
mongo = MongoClient("mongodb://mongodb:27017/", serverSelectionTimeoutMS=3000)
db = mongo["platform_db"]
collection = db["service_results"]

# ─── Prometheus Metrics ──────────────────────────────────────────
WRITE_COUNT = Counter(
    "service_c_writes_total",
    "Total MongoDB writes from Service C",
    ["status"]
)
WRITE_LATENCY = Histogram(
    "service_c_write_duration_seconds",
    "MongoDB write latency for Service C",
    buckets=[.005, .01, .025, .05, .1, .25, .5, 1.0, 2.5, 5.0]
)
REQUEST_LATENCY = Histogram(
    "service_c_request_duration_seconds",
    "Request latency for Service C",
    ["endpoint"],
    buckets=[.005, .01, .025, .05, .1, .25, .5, 1.0, 2.5, 5.0]
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

# ─── Routes ──────────────────────────────────────────────────────
@app.post("/store")
async def store(payload: dict):
    request_id = payload.get("request_id", str(uuid.uuid4()))

    doc = {
        "request_id": request_id,
        "result": payload.get("result"),
        "stored_at": time.time(),
        "service": "service_c"
    }

    write_start = time.perf_counter()
    try:
        collection.insert_one(doc)
        write_duration = time.perf_counter() - write_start

        WRITE_COUNT.labels(status="success").inc()
        WRITE_LATENCY.observe(write_duration)

        logger.info(
            "store_success",
            request_id=request_id,
            write_ms=round(write_duration * 1000, 2)
        )
        return {"status": "stored", "request_id": request_id}

    except (ConnectionFailure, ServerSelectionTimeoutError) as e:
        write_duration = time.perf_counter() - write_start
        WRITE_COUNT.labels(status="failure").inc()
        logger.error(
            "mongo_write_failed",
            request_id=request_id,
            error=str(e),
            write_ms=round(write_duration * 1000, 2)
        )
        return Response(status_code=503, content="Storage unavailable")

@app.get("/health")
def health():
    try:
        mongo.admin.command("ping")
        mongo_status = "healthy"
    except Exception:
        mongo_status = "degraded"
    return {
        "status": "healthy",
        "service": "service_c",
        "mongodb": mongo_status
    }

@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)