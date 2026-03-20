import time
import numpy as np
from pymongo import MongoClient
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler
from typing import List, Dict

class AnomalyDetector:
    """
    Unsupervised anomaly detection using Isolation Forest.
    Detects when metrics deviate significantly from baseline.
    Complements the supervised classifier — classifier identifies
    fault TYPE, anomaly detector identifies fault PRESENCE.
    """

    def __init__(self, contamination: float = 0.1):
        self.contamination = contamination
        self.models  = {}   # one model per service
        self.scalers = {}
        self.db = MongoClient("mongodb://localhost:27017/")["platform_db"]

    def fit_baseline(self, run_id: str):
        """
        Fit anomaly detector on pre_fault baseline metrics.
        Call this once per experiment before fault injection.
        """
        print(f"\n[ANOMALY] Fitting baseline for run: {run_id}")

        for service in ["service_a", "service_b", "service_c"]:
            docs = list(self.db["metrics_snapshots"].find({
                "run_id": run_id,
                "service": service,
                "time_window": "pre_fault",
                "data_quality": {"$exists": False}
            }, {"_id": 0}))

            if len(docs) < 3:
                print(f"[ANOMALY] {service}: insufficient baseline "
                      f"data ({len(docs)} docs)")
                continue

            X = self._docs_to_matrix(docs)
            if X is None or len(X) < 3:
                continue

            scaler = StandardScaler()
            X_scaled = scaler.fit_transform(X)

            model = IsolationForest(
                contamination=self.contamination,
                random_state=42,
                n_estimators=50
            )
            model.fit(X_scaled)

            self.models[service]  = model
            self.scalers[service] = scaler
            print(f"[ANOMALY] {service}: fitted on "
                  f"{len(docs)} baseline samples")

    def detect(self, run_id: str) -> Dict:
        """
        Detect anomalies across all time windows for a run.
        Returns anomaly rates per service per window.
        """
        print(f"\n[ANOMALY] Detecting anomalies for run: {run_id}")
        results = {}

        for service in ["service_a", "service_b", "service_c"]:
            if service not in self.models:
                results[service] = {"error": "no_baseline_model"}
                continue

            service_results = {}

            for window in ["pre_fault", "fault_active", "recovery"]:
                docs = list(self.db["metrics_snapshots"].find({
                    "run_id": run_id,
                    "service": service,
                    "time_window": window,
                    "data_quality": {"$exists": False}
                }, {"_id": 0}))

                if not docs:
                    service_results[window] = {
                        "anomaly_rate": 0,
                        "anomaly_count": 0,
                        "total": 0
                    }
                    continue

                X = self._docs_to_matrix(docs)
                if X is None:
                    continue

                X_scaled = self.scalers[service].transform(X)
                preds = self.model_predict(service, X_scaled)

                anomaly_count = int(np.sum(preds == -1))
                anomaly_rate  = round(anomaly_count / len(preds), 3)

                service_results[window] = {
                    "anomaly_rate":  anomaly_rate,
                    "anomaly_count": anomaly_count,
                    "total":         len(preds)
                }
                print(f"[ANOMALY] {service}/{window}: "
                      f"{anomaly_count}/{len(preds)} anomalies "
                      f"({anomaly_rate*100:.1f}%)")

            results[service] = service_results

        return results

    def model_predict(self, service: str, X_scaled: np.ndarray):
        """Predict anomalies — returns array of 1 (normal) or -1 (anomaly)"""
        return self.models[service].predict(X_scaled)

    def compute_anomaly_score(
        self, anomaly_results: dict
    ) -> dict:
        """
        Compute aggregate anomaly score per service.
        High fault_active anomaly rate = high confidence of fault.
        """
        scores = {}

        for service, windows in anomaly_results.items():
            if "error" in windows:
                scores[service] = None
                continue

            pre_rate   = windows.get(
                "pre_fault", {}
            ).get("anomaly_rate", 0)
            fault_rate = windows.get(
                "fault_active", {}
            ).get("anomaly_rate", 0)
            rec_rate   = windows.get(
                "recovery", {}
            ).get("anomaly_rate", 0)

            # Score = elevation of anomaly rate during fault
            # vs baseline anomaly rate
            elevation = fault_rate - pre_rate
            scores[service] = {
                "baseline_anomaly_rate": pre_rate,
                "fault_anomaly_rate":    fault_rate,
                "recovery_anomaly_rate": rec_rate,
                "anomaly_elevation":     round(elevation, 3),
                "fault_detected":        elevation > 0.2
            }
            print(f"[ANOMALY] {service}: elevation={elevation:.3f} "
                  f"→ fault_detected="
                  f"{scores[service]['fault_detected']}")

        return scores

    def save_results(
        self, run_id: str, experiment_id: str,
        anomaly_results: dict, scores: dict
    ):
        """Save anomaly detection results to MongoDB"""
        doc = {
            "experiment_id": experiment_id,
            "run_id": run_id,
            "analysis_type": "anomaly_detection",
            "computed_at": time.time(),
            "anomaly_results": anomaly_results,
            "anomaly_scores": scores
        }
        self.db["analysis_results"].insert_one(doc)
        print("[ANOMALY] Results saved to MongoDB ✅")
        return doc

    def _docs_to_matrix(self, docs: list):
        """Convert metric docs to numpy matrix"""
        rows = []
        for doc in docs:
            m = doc.get("metrics", {})
            row = [
                m.get("latency_p50_ms")    or 0,
                m.get("latency_p95_ms")    or 0,
                m.get("request_rate_rps")  or 0,
            ]
            rows.append(row)

        if not rows:
            return None

        return np.array(rows)


if __name__ == "__main__":
    from pymongo import MongoClient

    db = MongoClient("mongodb://localhost:27017/")["platform_db"]
    latest = db["experiment_runs"].find_one(sort=[("created_at", -1)])

    if latest:
        run_id        = latest["run_id"]
        experiment_id = latest["experiment_id"]

        detector = AnomalyDetector(contamination=0.15)
        detector.fit_baseline(run_id)
        anomaly_results = detector.detect(run_id)
        scores = detector.compute_anomaly_score(anomaly_results)
        detector.save_results(run_id, experiment_id,
                              anomaly_results, scores)
    else:
        print("No experiment runs found.")