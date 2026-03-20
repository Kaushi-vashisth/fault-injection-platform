from flask import Flask, jsonify
from flask_cors import CORS
from pymongo import MongoClient
import time

app = Flask(__name__)
CORS(app)

def get_db():
    return MongoClient("mongodb://localhost:27017/")["platform_db"]

# ── Experiments ───────────────────────────────────────────────────
@app.route("/api/experiments")
def get_experiments():
    db = get_db()
    runs = list(db["experiment_runs"].find(
        {"status": "completed"},
        {"_id": 0, "run_id": 1, "experiment_id": 1,
         "started_at": 1, "completed_at": 1}
    ).sort("started_at", -1).limit(20))
    return jsonify(runs)

# ── Scores ────────────────────────────────────────────────────────
@app.route("/api/scores")
def get_scores():
    db = get_db()
    scores = list(db["analysis_results"].find(
        {"analysis_type": "resilience_score"},
        {"_id": 0}
    ).sort("computed_at", -1).limit(20))
    return jsonify(scores)

# ── Alerts (live) ─────────────────────────────────────────────────
@app.route("/api/alerts")
def get_alerts():
    db = get_db()
    alerts = list(db["alerts"].find(
        {},
        {"_id": 0}
    ).sort("timestamp", -1).limit(50))
    return jsonify(alerts)

@app.route("/api/alerts/<run_id>")
def get_alerts_for_run(run_id):
    db = get_db()
    alerts = list(db["alerts"].find(
        {"run_id": run_id},
        {"_id": 0}
    ).sort("timestamp", -1))
    return jsonify(alerts)

@app.route("/api/alerts/active")
def get_active_alerts():
    db = get_db()
    alerts = list(db["alerts"].find(
        {"acknowledged": False},
        {"_id": 0}
    ).sort("timestamp", -1).limit(20))
    return jsonify(alerts)

# ── Live status ───────────────────────────────────────────────────
@app.route("/api/live/status")
def get_live_status():
    """Returns current running experiment if any"""
    db = get_db()
    running = db["experiment_runs"].find_one(
        {"status": "started"},
        {"_id": 0, "run_id": 1, "experiment_id": 1, "started_at": 1}
    )
    recent_metrics = list(db["metrics_snapshots"].find(
        {},
        {"_id": 0, "service": 1, "metrics": 1,
         "timestamp_epoch": 1, "run_id": 1}
    ).sort("timestamp_epoch", -1).limit(9))

    active_alerts = list(db["alerts"].find(
        {"acknowledged": False},
        {"_id": 0}
    ).sort("timestamp", -1).limit(10))

    return jsonify({
        "running_experiment": running,
        "recent_metrics":     recent_metrics,
        "active_alerts":      active_alerts,
        "server_time":        time.time()
    })

# ── Degradation ───────────────────────────────────────────────────
@app.route("/api/degradation/<run_id>")
def get_degradation(run_id):
    db = get_db()
    doc = db["analysis_results"].find_one(
        {"analysis_type": "degradation", "run_id": run_id},
        {"_id": 0}
    )
    return jsonify(doc or {})

# ── Propagation ───────────────────────────────────────────────────
@app.route("/api/propagation/<run_id>")
def get_propagation(run_id):
    db = get_db()
    doc = db["analysis_results"].find_one(
        {"analysis_type": "propagation", "run_id": run_id},
        {"_id": 0}
    )
    return jsonify(doc or {})

# ── ML ────────────────────────────────────────────────────────────
@app.route("/api/ml")
def get_ml_results():
    db = get_db()
    doc = db["analysis_results"].find_one(
        {"analysis_type": "ml_training"},
        {"_id": 0},
        sort=[("trained_at", -1)]
    )
    return jsonify(doc or {})

# ── Summary ───────────────────────────────────────────────────────
@app.route("/api/summary")
def get_summary():
    db = get_db()
    total_experiments = db["experiment_runs"].count_documents(
        {"status": "completed"}
    )
    total_faults = db["fault_events"].count_documents({})
    total_alerts = db["alerts"].count_documents({})
    scores = list(db["analysis_results"].find(
        {"analysis_type": "resilience_score"},
        {"final_resilience_score": 1, "_id": 0}
    ))
    avg_score = round(
        sum(s["final_resilience_score"] for s in scores) / len(scores), 3
    ) if scores else 0

    fault_counts = {}
    for fault in db["fault_events"].find(
        {}, {"fault_type": 1, "_id": 0}
    ):
        ft = fault.get("fault_type", "unknown")
        fault_counts[ft] = fault_counts.get(ft, 0) + 1

    return jsonify({
        "total_experiments":       total_experiments,
        "total_faults":            total_faults,
        "total_alerts":            total_alerts,
        "avg_resilience_score":    avg_score,
        "fault_type_distribution": fault_counts
    })

if __name__ == "__main__":
    print("Dashboard API running at http://localhost:5000")
    app.run(debug=False, port=5000, threaded=True)