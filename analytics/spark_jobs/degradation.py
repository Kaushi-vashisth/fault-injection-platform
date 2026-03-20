import time
import statistics
from pymongo import MongoClient

def compute_latency_degradation(
    metrics: list, run_id: str, baseline_stats: dict
) -> dict:
    print(f"\n[DEGRADATION] Computing latency degradation...")
    results = {}

    for service in ["service_a", "service_b", "service_c"]:
        if service not in baseline_stats:
            results[service] = {"latency_increase_pct": None}
            continue

        baseline_latency = baseline_stats[service].get("latency_mean")
        if not baseline_latency:
            results[service] = {"latency_increase_pct": None}
            continue

        fault_docs = [
            d for d in metrics
            if d.get("service") == service
            and d.get("time_window") == "fault_active"
        ]

        if not fault_docs:
            results[service] = {"latency_increase_pct": None}
            continue

        latencies = [
            d.get("metrics", {}).get("latency_p50_ms")
            for d in fault_docs
            if d.get("metrics", {}).get("latency_p50_ms") is not None
        ]

        if not latencies:
            results[service] = {"latency_increase_pct": None}
            continue

        fault_latency = statistics.mean(latencies)
        pct = round(
            (fault_latency - baseline_latency) / baseline_latency * 100, 2
        )
        results[service] = {
            "baseline_latency_ms": round(baseline_latency, 3),
            "fault_latency_ms": round(fault_latency, 3),
            "latency_increase_pct": pct
        }
        print(f"[DEGRADATION] {service}: {pct}% latency increase")

    return results


def compute_throughput_drop(
    metrics: list, run_id: str, baseline_stats: dict
) -> dict:
    print(f"\n[DEGRADATION] Computing throughput drop...")
    results = {}

    for service in ["service_a", "service_b", "service_c"]:
        if service not in baseline_stats:
            results[service] = {"throughput_drop_pct": None}
            continue

        baseline_rps = baseline_stats[service].get("rps_mean")
        if not baseline_rps:
            results[service] = {"throughput_drop_pct": None}
            continue

        fault_docs = [
            d for d in metrics
            if d.get("service") == service
            and d.get("time_window") == "fault_active"
        ]

        rps_vals = [
            d.get("metrics", {}).get("request_rate_rps")
            for d in fault_docs
            if d.get("metrics", {}).get("request_rate_rps") is not None
        ]

        if not rps_vals:
            results[service] = {"throughput_drop_pct": None}
            continue

        fault_rps = statistics.mean(rps_vals)
        pct = round(
            (baseline_rps - fault_rps) / baseline_rps * 100, 2
        )
        results[service] = {
            "baseline_rps": round(baseline_rps, 3),
            "fault_rps": round(fault_rps, 3),
            "throughput_drop_pct": pct
        }
        print(f"[DEGRADATION] {service}: {pct}% throughput drop")

    return results


def compute_error_rate_delta(metrics: list, run_id: str) -> dict:
    print(f"\n[DEGRADATION] Computing error rate delta...")
    db = MongoClient("mongodb://localhost:27017/")["platform_db"]
    results = {}

    for service in ["service_a", "service_b", "service_c"]:
        baseline_errors = db["log_entries"].count_documents({
            "run_id": run_id, "service": service,
            "time_window": "pre_fault", "level": "ERROR"
        })
        baseline_total = db["log_entries"].count_documents({
            "run_id": run_id, "service": service,
            "time_window": "pre_fault"
        })
        fault_errors = db["log_entries"].count_documents({
            "run_id": run_id, "service": service,
            "time_window": "fault_active", "level": "ERROR"
        })
        fault_total = db["log_entries"].count_documents({
            "run_id": run_id, "service": service,
            "time_window": "fault_active"
        })

        baseline_rate = (baseline_errors/baseline_total*100
                        if baseline_total > 0 else 0)
        fault_rate    = (fault_errors/fault_total*100
                        if fault_total > 0 else 0)
        delta = round(fault_rate - baseline_rate, 3)

        results[service] = {
            "baseline_error_rate_pct": round(baseline_rate, 3),
            "fault_error_rate_pct": round(fault_rate, 3),
            "error_rate_delta": delta
        }
        print(f"[DEGRADATION] {service}: error delta = {delta}%")

    return results


def save_degradation_results(
    run_id: str, experiment_id: str,
    latency: dict, throughput: dict, errors: dict
) -> dict:
    db = MongoClient("mongodb://localhost:27017/")["platform_db"]
    doc = {
        "experiment_id": experiment_id,
        "run_id": run_id,
        "analysis_type": "degradation",
        "computed_at": time.time(),
        "latency_degradation": latency,
        "throughput_drop": throughput,
        "error_rate_delta": errors
    }
    db["analysis_results"].insert_one(doc)
    print(f"[DEGRADATION] Results saved ✅")
    return doc