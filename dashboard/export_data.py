
import json
import time
from pymongo import MongoClient

def export_dashboard_data():
    db = MongoClient("mongodb://localhost:27017/")["platform_db"]

    # ── Experiments ───────────────────────────────────────────────
    experiments = list(db["experiment_runs"].find(
        {"status": "completed"},
        {"_id": 0, "run_id": 1, "experiment_id": 1,
         "started_at": 1, "completed_at": 1}
    ).sort("started_at", -1).limit(20))

    # ── Resilience Scores ─────────────────────────────────────────
    scores = list(db["analysis_results"].find(
        {"analysis_type": "resilience_score"},
        {"_id": 0, "run_id": 1, "experiment_id": 1,
         "final_resilience_score": 1, "component_scores": 1,
         "score_interpretation": 1, "computed_at": 1}
    ).sort("computed_at", -1).limit(20))

    # ── Fault Events ──────────────────────────────────────────────
    faults = list(db["fault_events"].find(
        {},
        {"_id": 0, "run_id": 1, "fault_type": 1,
         "target_service": 1, "injected_at": 1,
         "rolled_back_at": 1, "status": 1}
    ).sort("injected_at", -1).limit(20))

    # ── ML Results 
    ml = db["analysis_results"].find_one(
        {"analysis_type": "ml_training"},
        {"_id": 0},
        sort=[("trained_at", -1)]
    )

    # ── Degradation Results ───────────────────────────────────────
    degradations = list(db["analysis_results"].find(
        {"analysis_type": "degradation"},
        {"_id": 0, "run_id": 1, "experiment_id": 1,
         "latency_degradation": 1, "throughput_drop": 1,
         "computed_at": 1}
    ).sort("computed_at", -1).limit(20))

    # ── Propagation Results ───────────────────────────────────────
    propagations = list(db["analysis_results"].find(
        {"analysis_type": "propagation"},
        {"_id": 0, "run_id": 1, "experiment_id": 1,
         "blast_radius": 1, "propagation_graph": 1,
         "computed_at": 1}
    ).sort("computed_at", -1).limit(10))

    # ── Summary ───────────────────────────────────────────────────
    fault_counts = {}
    for fault in db["fault_events"].find({}, {"fault_type": 1, "_id": 0}):
        ft = fault.get("fault_type", "unknown")
        fault_counts[ft] = fault_counts.get(ft, 0) + 1

    avg_score = round(
        sum(s["final_resilience_score"] for s in scores) / len(scores), 3
    ) if scores else 0

    summary = {
        "total_experiments": len(experiments),
        "total_faults": len(faults),
        "avg_resilience_score": avg_score,
        "fault_type_distribution": fault_counts,
        "exported_at": time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    }

    # ── Write to JSON ─────────────────────────────────────────────
    data = {
        "summary": summary,
        "experiments": experiments,
        "scores": scores,
        "faults": faults,
        "ml": ml,
        "degradations": degradations,
        "propagations": propagations
    }

    output_path = "dashboard/public/data.json"
    with open(output_path, "w") as f:
        json.dump(data, f, indent=2, default=str)

    print(f"✅ Dashboard data exported to {output_path}")
    print(f"   Experiments: {len(experiments)}")
    print(f"   Scores:      {len(scores)}")
    print(f"   Faults:      {len(faults)}")
    print(f"   Avg Score:   {avg_score}")

if __name__ == "__main__":
    export_dashboard_data()