import time
import numpy as np
from pymongo import MongoClient
from typing import List, Dict

FAULT_LABEL_MAP = {
    "cpu":     0,
    "memory":  1,
    "network": 2,
    "crash":   3
}

LABEL_NAME_MAP = {v: k for k, v in FAULT_LABEL_MAP.items()}

def extract_features_for_run(run_id: str) -> Dict:
    """
    Extract ML features from a single experiment run.
    Features are statistical summaries of metrics across time windows.
    """
    db = MongoClient("mongodb://localhost:27017/")["platform_db"]

    # Get fault label
    fault_event = db["fault_events"].find_one({"run_id": run_id})
    if not fault_event:
        return None

    fault_type   = fault_event.get("fault_type", "unknown")
    label        = FAULT_LABEL_MAP.get(fault_type, -1)
    target_service = fault_event.get("target_service", "service_b")

    # Get metrics for this run
    metrics = list(db["metrics_snapshots"].find(
        {"run_id": run_id, "data_quality": {"$exists": False}},
        {"_id": 0}
    ))

    if not metrics:
        return None

    features = {}

    # Extract features per service per window
    for service in ["service_a", "service_b", "service_c"]:
        for window in ["pre_fault", "fault_active", "recovery"]:
            window_docs = [
                d for d in metrics
                if d.get("service") == service
                and d.get("time_window") == window
            ]

            prefix = f"{service}_{window}"
            features.update(
                _compute_window_features(window_docs, prefix)
            )

    # Add delta features (fault_active - pre_fault)
    for service in ["service_a", "service_b", "service_c"]:
        pre_lat = features.get(f"{service}_pre_fault_latency_mean", 0) or 0
        flt_lat = features.get(f"{service}_fault_active_latency_mean", 0) or 0
        pre_rps = features.get(f"{service}_pre_fault_rps_mean", 0) or 0
        flt_rps = features.get(f"{service}_fault_active_rps_mean", 0) or 0

        features[f"{service}_latency_delta"] = round(flt_lat - pre_lat, 4)
        features[f"{service}_rps_delta"] = round(flt_rps - pre_rps, 4)
        features[f"{service}_latency_increase_pct"] = round(
            (flt_lat - pre_lat) / pre_lat * 100
            if pre_lat > 0 else 0, 4
        )

    # Add experiment metadata features
    features["fault_duration_sec"] = fault_event.get(
        "parameters", {}
    ).get("duration_sec", 0)
    features["is_target_service_b"] = 1 if target_service == "service_b" else 0

    return {
        "run_id": run_id,
        "experiment_id": fault_event.get("experiment_id"),
        "fault_type": fault_type,
        "label": label,
        "features": features
    }


def _compute_window_features(docs: list, prefix: str) -> dict:
    """Compute statistical features for a time window"""
    if not docs:
        return {
            f"{prefix}_latency_mean": 0,
            f"{prefix}_latency_std": 0,
            f"{prefix}_latency_max": 0,
            f"{prefix}_rps_mean": 0,
            f"{prefix}_rps_std": 0,
            f"{prefix}_count": 0
        }

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

    def safe_stats(vals):
        if not vals:
            return 0, 0, 0
        arr = np.array(vals)
        return round(float(np.mean(arr)), 4), \
               round(float(np.std(arr)), 4), \
               round(float(np.max(arr)), 4)

    lat_mean, lat_std, lat_max = safe_stats(latencies)
    rps_mean, rps_std, rps_max = safe_stats(rps_vals)

    return {
        f"{prefix}_latency_mean": lat_mean,
        f"{prefix}_latency_std":  lat_std,
        f"{prefix}_latency_max":  lat_max,
        f"{prefix}_rps_mean":     rps_mean,
        f"{prefix}_rps_std":      rps_std,
        f"{prefix}_count":        len(docs)
    }


def extract_all_features() -> List[Dict]:
    """
    Extract features from ALL completed experiment runs.
    Returns list of feature dicts ready for ML training.
    """
    db = MongoClient("mongodb://localhost:27017/")["platform_db"]

    # Get all completed runs
    runs = list(db["experiment_runs"].find(
        {"status": "completed"},
        {"run_id": 1, "experiment_id": 1, "_id": 0}
    ))

    print(f"[FEATURES] Found {len(runs)} completed runs")

    feature_rows = []
    for run in runs:
        row = extract_features_for_run(run["run_id"])
        if row and row["label"] >= 0:
            feature_rows.append(row)
            print(f"[FEATURES] Extracted: {run['run_id'][:8]}... "
                  f"→ {row['fault_type']}")

    print(f"[FEATURES] Total feature rows: {len(feature_rows)}")
    return feature_rows


def features_to_matrix(feature_rows: List[Dict]):
    """
    Convert feature rows to X matrix and y labels for sklearn.
    Returns X (numpy array), y (numpy array), feature_names (list)
    """
    if not feature_rows:
        return None, None, None

    feature_names = sorted(feature_rows[0]["features"].keys())

    X = np.array([
        [row["features"].get(f, 0) or 0 for f in feature_names]
        for row in feature_rows
    ])
    y = np.array([row["label"] for row in feature_rows])

    print(f"[FEATURES] Matrix shape: {X.shape}")
    print(f"[FEATURES] Labels: {y}")

    return X, y, feature_names


if __name__ == "__main__":
    rows = extract_all_features()
    X, y, names = features_to_matrix(rows)
    if X is not None:
        print(f"\nFeature matrix: {X.shape}")
        print(f"Labels: {y}")
        print(f"Feature count: {len(names)}")