import time
import threading
import statistics
from pymongo import MongoClient
from realtime.alert_manager import AlertManager
from analytics.ml.feature_extraction import FAULT_LABEL_MAP, LABEL_NAME_MAP
import pickle
import os
import numpy as np

MODEL_PATH  = "analytics/ml/trained_model.pkl"
SCALER_PATH = "analytics/ml/trained_scaler.pkl"

class RealTimeDetector:
    """
    Background thread that continuously monitors metrics
    and detects anomalies in real-time during experiments.
    
    Detection pipeline:
    1. Pull latest metrics from MongoDB every 10s
    2. Compare against baseline statistics
    3. If anomaly detected → run ML classifier
    4. Fire alert to AlertManager
    """

    def __init__(
        self,
        run_id: str,
        experiment_id: str,
        baseline_stats: dict,
        check_interval_sec: int = 10,
        mongo_uri: str = "mongodb://localhost:27017/"
    ):
        self.run_id        = run_id
        self.experiment_id = experiment_id
        self.baseline_stats = baseline_stats
        self.interval      = check_interval_sec
        self.db            = MongoClient(mongo_uri)["platform_db"]
        self.alert_manager = AlertManager(mongo_uri)
        self._stop_event   = threading.Event()
        self._thread       = None
        self.model         = None
        self.scaler        = None
        self._load_model()
        self.detection_count = 0
        self.alert_count     = 0

    def start(self):
        """Start background detection thread"""
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._detect_loop,
            daemon=True,
            name="RealTimeDetector"
        )
        self._thread.start()
        print(f"[DETECTOR] Started for run: {self.run_id[:8]}...")

    def stop(self):
        """Stop detection thread"""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=15)
        print(f"[DETECTOR] Stopped — "
              f"{self.detection_count} checks, "
              f"{self.alert_count} alerts fired")

    def _detect_loop(self):
        """Main detection loop"""
        while not self._stop_event.is_set():
            try:
                self._run_detection_cycle()
                self.detection_count += 1
            except Exception as e:
                print(f"[DETECTOR] Error in detection cycle: {e}")
            self._stop_event.wait(timeout=self.interval)

    def _run_detection_cycle(self):
        """Single detection cycle — check all services"""
        now = time.time()
        window_start = now - self.interval * 2

        for service in ["service_a", "service_b", "service_c"]:
            # Get recent metrics
            recent_docs = list(self.db["metrics_snapshots"].find(
                {
                    "run_id": self.run_id,
                    "service": service,
                    "timestamp_epoch": {"$gte": window_start},
                    "data_quality": {"$exists": False}
                },
                {"_id": 0}
            ).sort("timestamp_epoch", -1).limit(5))

            if not recent_docs:
                continue

            # Check for anomalies
            anomalies = self._check_anomalies(service, recent_docs)

            if anomalies:
                self.alert_count += 1
                # Try ML classification
                fault_prediction = self._classify_fault()

                # Fire alert
                self.alert_manager.create_alert(
                    run_id        = self.run_id,
                    experiment_id = self.experiment_id,
                    alert_type    = "anomaly_detected",
                    level         = self._determine_level(anomalies),
                    service       = service,
                    message       = self._build_message(
                        service, anomalies, fault_prediction
                    ),
                    details       = {
                        "anomalies":        anomalies,
                        "fault_prediction": fault_prediction,
                        "checked_at":       now
                    }
                )

    def _check_anomalies(
        self, service: str, recent_docs: list
    ) -> list:
        """Check if recent metrics exceed baseline thresholds"""
        if service not in self.baseline_stats:
            return []

        baseline = self.baseline_stats[service]
        anomalies = []

        latencies = [
            d.get("metrics", {}).get("latency_p50_ms")
            for d in recent_docs
            if d.get("metrics", {}).get("latency_p50_ms") is not None
        ]
        rps_vals = [
            d.get("metrics", {}).get("request_rate_rps")
            for d in recent_docs
            if d.get("metrics", {}).get("request_rate_rps") is not None
        ]

        if latencies:
            avg_latency  = statistics.mean(latencies)
            threshold    = baseline.get("latency_threshold", 999)
            baseline_lat = baseline.get("latency_mean", 0)

            if avg_latency > threshold:
                increase_pct = round(
                    (avg_latency - baseline_lat) /
                    baseline_lat * 100, 1
                ) if baseline_lat > 0 else 0

                anomalies.append({
                    "metric":        "latency",
                    "current_value": round(avg_latency, 2),
                    "threshold":     round(threshold, 2),
                    "baseline":      round(baseline_lat, 2),
                    "increase_pct":  increase_pct
                })

        if rps_vals:
            avg_rps      = statistics.mean(rps_vals)
            baseline_rps = baseline.get("rps_mean", 0)

            # Alert if RPS drops more than 30%
            if baseline_rps > 0:
                drop_pct = (baseline_rps - avg_rps) / baseline_rps * 100
                if drop_pct > 30:
                    anomalies.append({
                        "metric":     "throughput",
                        "current_value": round(avg_rps, 3),
                        "baseline":   round(baseline_rps, 3),
                        "drop_pct":   round(drop_pct, 1)
                    })

        return anomalies

    def _classify_fault(self) -> dict:
        """Run ML classifier on current run data"""
        if not self.model:
            return {"fault_type": "unknown", "confidence": 0}

        try:
            from analytics.ml.feature_extraction import (
                extract_features_for_run
            )
            row = extract_features_for_run(self.run_id)
            if not row:
                return {"fault_type": "unknown", "confidence": 0}

            feature_names = sorted(row["features"].keys())
            x = np.array([[
                row["features"].get(f, 0) or 0
                for f in feature_names
            ]])
            x_scaled = self.scaler.transform(x)
            pred_label = int(self.model.predict(x_scaled)[0])
            pred_proba = self.model.predict_proba(x_scaled)[0]
            confidence = round(float(max(pred_proba)), 3)

            return {
                "fault_type": LABEL_NAME_MAP.get(
                    pred_label, "unknown"
                ),
                "confidence": confidence
            }
        except Exception as e:
            return {"fault_type": "unknown", "confidence": 0}

    def _determine_level(self, anomalies: list) -> str:
        """Determine alert level based on anomaly severity"""
        for a in anomalies:
            if a.get("increase_pct", 0) > 100:
                return "CRITICAL"
            if a.get("drop_pct", 0) > 50:
                return "CRITICAL"
        return "WARNING"

    def _build_message(
        self,
        service: str,
        anomalies: list,
        fault_prediction: dict
    ) -> str:
        parts = []
        for a in anomalies:
            if a["metric"] == "latency":
                parts.append(
                    f"Latency {a['increase_pct']}% above baseline"
                )
            elif a["metric"] == "throughput":
                parts.append(
                    f"Throughput dropped {a['drop_pct']}%"
                )

        fault_type = fault_prediction.get("fault_type", "unknown")
        confidence = fault_prediction.get("confidence", 0)

        if fault_type != "unknown":
            parts.append(
                f"Predicted fault: {fault_type} "
                f"({int(confidence*100)}% confidence)"
            )

        return f"{service}: " + " | ".join(parts)

    def _load_model(self):
        """Load trained ML model"""
        if os.path.exists(MODEL_PATH) and os.path.exists(SCALER_PATH):
            with open(MODEL_PATH, "rb") as f:
                self.model = pickle.load(f)
            with open(SCALER_PATH, "rb") as f:
                self.scaler = pickle.load(f)
            print("[DETECTOR] ML model loaded ✅")
        else:
            print("[DETECTOR] No ML model found — "
                  "detection without classification")