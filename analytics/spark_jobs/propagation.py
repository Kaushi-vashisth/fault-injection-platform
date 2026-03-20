import time
from pymongo import MongoClient

DEPENDENCY_GRAPH = {
    "service_a": ["service_b"],
    "service_b": ["service_c"],
    "service_c": []
}

def detect_propagation(
    metrics: list, run_id: str,
    baseline_stats: dict, fault_target: str
) -> dict:
    print(f"\n[PROPAGATION] Detecting for run: {run_id}")
    db = MongoClient("mongodb://localhost:27017/")["platform_db"]
    fault_event = db["fault_events"].find_one({"run_id": run_id})

    if not fault_event:
        return {}

    t_inject = fault_event.get("injected_at", 0)
    results  = {}

    for service in ["service_a", "service_b", "service_c"]:
        if service not in baseline_stats:
            results[service] = {"affected": False,
                                "propagation_lag_sec": None}
            continue

        threshold = baseline_stats[service].get("latency_threshold", 999)

        fault_docs = sorted([
            d for d in metrics
            if d.get("service") == service
            and d.get("timestamp_epoch", 0) >= t_inject
        ], key=lambda x: x.get("timestamp_epoch", 0))

        first_deviation = None
        for doc in fault_docs:
            lat = doc.get("metrics", {}).get("latency_p50_ms")
            if lat is not None and lat > threshold:
                first_deviation = doc.get("timestamp_epoch")
                break

        if first_deviation:
            lag = round(first_deviation - t_inject, 2)
            results[service] = {
                "affected": True,
                "propagation_lag_sec": lag,
                "is_direct_target": service == fault_target
            }
            print(f"[PROPAGATION] {service}: affected (lag={lag}s)")
        else:
            results[service] = {
                "affected": False,
                "propagation_lag_sec": None,
                "is_direct_target": service == fault_target
            }
            print(f"[PROPAGATION] {service}: not affected")

    return results


def build_propagation_graph(
    propagation_results: dict, fault_target: str
) -> dict:
    nodes = []
    edges = []

    for service, result in propagation_results.items():
        nodes.append({
            "id": service,
            "affected": result.get("affected", False),
            "propagation_lag_sec": result.get("propagation_lag_sec"),
            "is_fault_origin": service == fault_target
        })

    for source, targets in DEPENDENCY_GRAPH.items():
        for target in targets:
            edges.append({
                "source": source,
                "target": target,
                "propagation_occurred": (
                    propagation_results.get(source, {})
                    .get("affected", False)
                    and
                    propagation_results.get(target, {})
                    .get("affected", False)
                )
            })

    return {"nodes": nodes, "edges": edges, "fault_origin": fault_target}


def compute_blast_radius(propagation_results: dict) -> dict:
    total    = len(propagation_results)
    affected = [s for s, r in propagation_results.items()
                if r.get("affected", False)]
    return {
        "total_services": total,
        "affected_services": affected,
        "affected_count": len(affected),
        "blast_radius_pct": round(len(affected) / total * 100, 1)
        if total > 0 else 0
    }


def save_propagation_results(
    run_id: str, experiment_id: str,
    propagation: dict, graph: dict, blast_radius: dict
) -> dict:
    db = MongoClient("mongodb://localhost:27017/")["platform_db"]
    doc = {
        "experiment_id": experiment_id,
        "run_id": run_id,
        "analysis_type": "propagation",
        "computed_at": time.time(),
        "propagation_per_service": propagation,
        "propagation_graph": graph,
        "blast_radius": blast_radius
    }
    db["analysis_results"].insert_one(doc)
    print(f"[PROPAGATION] Results saved ✅")
    return doc