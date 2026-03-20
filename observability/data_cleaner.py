import time
import statistics
from pymongo import MongoClient

class ObservabilityDataCleaner:

    def __init__(self, mongo_uri: str = "mongodb://localhost:27017/"):
        self.db = MongoClient(mongo_uri)["platform_db"]

    def clean_experiment(self, run_id: str) -> dict:
        """
        Run all cleaning steps for a completed experiment.
        Returns a report of cleaning actions taken.
        """
        print(f"\n[CLEANER] Cleaning data for run: {run_id}")
        report = {
            "run_id": run_id,
            "cleaned_at": time.time()
        }

        # Step 1: Mark invalid metric values
        invalid = self.db["metrics_snapshots"].update_many(
            {
                "run_id": run_id,
                "$or": [
                    {"metrics.latency_p50_ms": None},
                    {"metrics.request_rate_rps": {"$lt": 0}},
                ]
            },
            {"$set": {"data_quality": "invalid"}}
        )
        report["invalid_marked"] = invalid.modified_count
        print(f"[CLEANER] Invalid metrics marked: {invalid.modified_count}")

        # Step 2: Detect scrape gaps
        gaps = self._detect_gaps(run_id)
        report["gaps_detected"] = len(gaps)
        if gaps:
            self.db["data_quality_events"].insert_many(gaps)
            print(f"[CLEANER] Gaps detected: {len(gaps)}")

        # Step 3: Tag baseline outliers
        outliers = self._tag_baseline_outliers(run_id)
        report["baseline_outliers_tagged"] = outliers
        print(f"[CLEANER] Baseline outliers tagged: {outliers}")

        # Step 4: Count total clean documents
        total = self.db["metrics_snapshots"].count_documents({
            "run_id": run_id,
            "data_quality": {"$exists": False}
        })
        report["clean_documents"] = total
        print(f"[CLEANER] Clean documents: {total}")
        print(f"[CLEANER] Cleaning complete ✅")

        return report

    def _detect_gaps(self, run_id: str) -> list:
        """
        Find time gaps > 3x scrape interval between snapshots.
        These indicate missed scrapes or container downtime.
        """
        gaps = []
        expected_interval = 5   # seconds
        gap_threshold = expected_interval * 3

        for service in ["service_a", "service_b", "service_c"]:
            docs = list(
                self.db["metrics_snapshots"]
                .find(
                    {"run_id": run_id, "service": service},
                    {"timestamp_epoch": 1}
                )
                .sort("timestamp_epoch", 1)
            )

            timestamps = [d["timestamp_epoch"] for d in docs]

            for i in range(1, len(timestamps)):
                delta = timestamps[i] - timestamps[i - 1]
                if delta > gap_threshold:
                    gaps.append({
                        "run_id": run_id,
                        "service": service,
                        "type": "scrape_gap",
                        "gap_start": timestamps[i - 1],
                        "gap_end": timestamps[i],
                        "gap_duration_sec": round(delta, 2),
                        "detected_at": time.time()
                    })

        return gaps

    def _tag_baseline_outliers(self, run_id: str) -> int:
        """
        Tag statistical outliers in baseline window.
        Outlier = value > mean + 5 * std dev.
        Does NOT delete — outliers are flagged for Spark to handle.
        """
        total_tagged = 0

        for service in ["service_a", "service_b", "service_c"]:
            docs = list(
                self.db["metrics_snapshots"].find({
                    "run_id": run_id,
                    "service": service,
                    "time_window": "pre_fault",
                    "data_quality": {"$exists": False}
                })
            )

            if len(docs) < 5:
                continue

            latencies = [
                d["metrics"].get("latency_p50_ms")
                for d in docs
                if d["metrics"].get("latency_p50_ms") is not None
            ]

            if len(latencies) < 5:
                continue

            mean = statistics.mean(latencies)
            std = statistics.stdev(latencies)
            threshold = mean + 5 * std

            outlier_ids = [
                d["_id"] for d in docs
                if (d["metrics"].get("latency_p50_ms") or 0) > threshold
            ]

            if outlier_ids:
                self.db["metrics_snapshots"].update_many(
                    {"_id": {"$in": outlier_ids}},
                    {"$set": {"data_quality": "baseline_outlier"}}
                )
                total_tagged += len(outlier_ids)

        return total_tagged

    def get_clean_metrics(self, run_id: str, service: str) -> list:
        """
        Retrieve clean metrics for a service in a run.
        Excludes invalid and outlier documents.
        """
        return list(
            self.db["metrics_snapshots"].find(
                {
                    "run_id": run_id,
                    "service": service,
                    "data_quality": {"$exists": False}
                },
                {"_id": 0}
            ).sort("timestamp_epoch", 1)
        )

    def get_cleaning_report(self, run_id: str) -> dict:
        """Get summary statistics for data quality"""
        total = self.db["metrics_snapshots"].count_documents(
            {"run_id": run_id}
        )
        invalid = self.db["metrics_snapshots"].count_documents(
            {"run_id": run_id, "data_quality": "invalid"}
        )
        outliers = self.db["metrics_snapshots"].count_documents(
            {"run_id": run_id, "data_quality": "baseline_outlier"}
        )
        clean = total - invalid - outliers

        return {
            "run_id": run_id,
            "total_documents": total,
            "invalid": invalid,
            "baseline_outliers": outliers,
            "clean": clean,
            "quality_pct": round((clean / total * 100) if total > 0 else 0, 1)
        }


if __name__ == "__main__":
    cleaner = ObservabilityDataCleaner()

    # Test with most recent experiment run
    from pymongo import MongoClient
    db = MongoClient("mongodb://localhost:27017/")["platform_db"]
    latest_run = db["experiment_runs"].find_one(
        sort=[("created_at", -1)]
    )

    if latest_run:
        run_id = latest_run["run_id"]
        print(f"Cleaning run: {run_id}")
        report = cleaner.clean_experiment(run_id)
        print(f"\nReport: {report}")
    else:
        print("No experiment runs found in MongoDB yet.")