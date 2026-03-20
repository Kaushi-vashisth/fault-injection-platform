from pymongo import MongoClient
import statistics

MONGO_URI = "mongodb://localhost:27017/"

def get_db():
    return MongoClient(MONGO_URI)["platform_db"]

def load_metrics(run_id: str = None) -> list:
    db = get_db()
    query = {"run_id": run_id} if run_id else {}
    docs = list(db["metrics_snapshots"].find(query, {"_id": 0}))
    print(f"[ANALYTICS] Loaded metrics: {len(docs)} documents")
    return docs

def load_fault_events(experiment_id: str = None) -> list:
    db = get_db()
    query = {"experiment_id": experiment_id} if experiment_id else {}
    return list(db["fault_events"].find(query, {"_id": 0}))

def load_experiment_runs(experiment_id: str = None) -> list:
    db = get_db()
    query = {"experiment_id": experiment_id} if experiment_id else {}
    return list(db["experiment_runs"].find(query, {"_id": 0}))

def get_baseline_stats(run_id: str) -> dict:
    docs = load_metrics(run_id)
    baseline_docs = [
        d for d in docs
        if d.get("time_window") == "pre_fault"
        and not d.get("data_quality")
    ]

    stats = {}
    for service in ["service_a", "service_b", "service_c"]:
        svc_docs = [d for d in baseline_docs if d.get("service") == service]
        if len(svc_docs) < 2:
            continue

        latencies = [
            d.get("metrics", {}).get("latency_p50_ms")
            for d in svc_docs
            if d.get("metrics", {}).get("latency_p50_ms") is not None
        ]
        rps_vals = [
            d.get("metrics", {}).get("request_rate_rps")
            for d in svc_docs
            if d.get("metrics", {}).get("request_rate_rps") is not None
        ]

        if len(latencies) < 2:
            lat_mean, lat_std = (latencies[0] if latencies else 5.0), 1.0
        else:
            lat_mean = statistics.mean(latencies)
            lat_std  = statistics.stdev(latencies)

        rps_mean = statistics.mean(rps_vals) if rps_vals else 0.0

        stats[service] = {
            "latency_mean": lat_mean,
            "latency_std":  lat_std,
            "rps_mean":     rps_mean,
            "latency_threshold": lat_mean + 2 * lat_std
        }

    print(f"[ANALYTICS] Baseline stats computed for "
          f"{len(stats)} services")
    return stats

# Keep Spark session as no-op for pipeline compatibility
def create_spark_session(app_name: str = None):
    return None