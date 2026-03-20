import time
import statistics
from pymongo import MongoClient

def compute_mttr(metrics: list, run_id: str, baseline_stats: dict) -> dict:
    print(f"\n[MTTR] Computing for run: {run_id}")
    db = MongoClient("mongodb://localhost:27017/")["platform_db"]
    fault_event = db["fault_events"].find_one({"run_id": run_id})

    if not fault_event:
        print("[MTTR] No fault event found")
        return {}

    t_inject   = fault_event.get("injected_at", 0)
    t_rollback = fault_event.get("rolled_back_at", 0)

    if not t_inject or not t_rollback:
        print("[MTTR] Missing timestamps")
        return {}

    results = {}
    for service in ["service_a", "service_b", "service_c"]:
        if service not in baseline_stats:
            results[service] = None
            continue

        baseline_latency = baseline_stats[service].get("latency_mean", 5.0)
        recovery_threshold = baseline_latency * 1.10

        recovery_docs = sorted([
            d for d in metrics
            if d.get("service") == service
            and d.get("timestamp_epoch", 0) >= t_rollback
        ], key=lambda x: x.get("timestamp_epoch", 0))

        recovery_time = None
        for doc in recovery_docs:
            lat = doc.get("metrics", {}).get("latency_p50_ms")
            if lat is not None and lat <= recovery_threshold:
                recovery_time = doc.get("timestamp_epoch")
                break

        if recovery_time:
            mttr = round(recovery_time - t_rollback, 2)
            results[service] = mttr
            print(f"[MTTR] {service}: {mttr}s")
        else:
            results[service] = None
            print(f"[MTTR] {service}: did not recover in window")

    return results


def compute_fault_window_stats(metrics: list, run_id: str) -> dict:
    results = {}
    windows = ["pre_fault", "fault_active", "recovery"]

    for service in ["service_a", "service_b", "service_c"]:
        results[service] = {}
        for window in windows:
            docs = [
                d for d in metrics
                if d.get("service") == service
                and d.get("time_window") == window
                and not d.get("data_quality")
            ]
            if not docs:
                results[service][window] = {
                    "count": 0,
                    "latency_mean": None,
                    "rps_mean": None
                }
                continue

            latencies = [
                d.get("metrics", {}).get("latency_p50_ms")
                for d in docs
                if d.get("metrics", {}).get("latency_p50_ms") is not None
            ]
            rps_vals = [
                d.get("metrics", {}).get("request_rate_rps")
                for d in docs
                if d.get("metrics", {}).get("request_rate_rps") is not None
            ]

            results[service][window] = {
                "count": len(docs),
                "latency_mean": round(statistics.mean(latencies), 3)
                    if latencies else None,
                "rps_mean": round(statistics.mean(rps_vals), 3)
                    if rps_vals else None
            }

    return results


def save_mttr_results(
    run_id: str, experiment_id: str,
    mttr_results: dict, window_stats: dict
) -> dict:
    db = MongoClient("mongodb://localhost:27017/")["platform_db"]
    doc = {
        "experiment_id": experiment_id,
        "run_id": run_id,
        "analysis_type": "mttr",
        "computed_at": time.time(),
        "mttr_per_service": mttr_results,
        "window_stats": window_stats
    }
    db["analysis_results"].insert_one(doc)
    print(f"[MTTR] Results saved ✅")
    return doc