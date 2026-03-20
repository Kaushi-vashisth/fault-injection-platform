import time
import requests
from pymongo import MongoClient
from typing import Optional

METRIC_QUERIES = {
    "request_rate_rps": 'rate(service_a_requests_total[30s])',
    "latency_p50_ms":   'histogram_quantile(0.50, rate(service_a_request_duration_seconds_bucket[30s])) * 1000',
    "latency_p95_ms":   'histogram_quantile(0.95, rate(service_a_request_duration_seconds_bucket[30s])) * 1000',
    "latency_p99_ms":   'histogram_quantile(0.99, rate(service_a_request_duration_seconds_bucket[30s])) * 1000',
    "cpu_stress_active": 'rate(service_b_compute_duration_seconds_sum[30s])',
    "write_success_rate": 'rate(service_c_writes_total{status="success"}[30s])',
    "write_failure_rate": 'rate(service_c_writes_total{status="failure"}[30s])',
}

SERVICE_METRIC_QUERIES = {
    "service_a": {
        "request_rate_rps":  'rate(service_a_requests_total[30s])',
        "latency_p50_ms":    'histogram_quantile(0.50, rate(service_a_request_duration_seconds_bucket[30s])) * 1000',
        "latency_p95_ms":    'histogram_quantile(0.95, rate(service_a_request_duration_seconds_bucket[30s])) * 1000',
        "latency_p99_ms":    'histogram_quantile(0.99, rate(service_a_request_duration_seconds_bucket[30s])) * 1000',
    },
    "service_b": {
        "request_rate_rps":  'rate(service_b_requests_total[30s])',
        "latency_p50_ms":    'histogram_quantile(0.50, rate(service_b_request_duration_seconds_bucket[30s])) * 1000',
        "latency_p95_ms":    'histogram_quantile(0.95, rate(service_b_request_duration_seconds_bucket[30s])) * 1000',
        "latency_p99_ms":    'histogram_quantile(0.99, rate(service_b_request_duration_seconds_bucket[30s])) * 1000',
        "compute_duration_ms": 'rate(service_b_compute_duration_seconds_sum[30s]) * 1000',
    },
    "service_c": {
    "request_rate_rps":    'rate(service_c_request_duration_seconds_count{endpoint="/store"}[30s])',
    "latency_p50_ms":      'histogram_quantile(0.50, rate(service_c_request_duration_seconds_bucket{endpoint="/store"}[30s])) * 1000',
    "latency_p95_ms":      'histogram_quantile(0.95, rate(service_c_request_duration_seconds_bucket{endpoint="/store"}[30s])) * 1000',
    "write_success_rate":  'rate(service_c_writes_total{status="success"}[30s])',
    "write_failure_rate":  'rate(service_c_writes_total{status="failure"}[30s])',
    "write_latency_p95_ms": 'histogram_quantile(0.95, rate(service_c_write_duration_seconds_bucket[30s])) * 1000'
    
    }
}

class MetricsSnapshotCollector:

    def __init__(
        self,
        prometheus_url: str = "http://localhost:9090",
        mongo_uri: str = "mongodb://localhost:27017/",
        interval_sec: int = 5
    ):
        self.prom_url = prometheus_url
        self.db = MongoClient(mongo_uri)["platform_db"]
        self.interval = interval_sec
        self.collection = self.db["metrics_snapshots"]
        self._running = False

    def start(self, experiment_id: str, run_id: str):
        """Start continuous metrics collection"""
        self._running = True
        print(f"[METRICS] Starting collection for experiment {experiment_id}")

        while self._running:
            try:
                snapshots = self._collect_snapshot(experiment_id, run_id)
                if snapshots:
                    self.collection.insert_many(snapshots)
                    print(f"[METRICS] Collected {len(snapshots)} snapshots")
            except Exception as e:
                print(f"[METRICS] Collection error: {e}")
            time.sleep(self.interval)

    def stop(self):
        self._running = False
        print("[METRICS] Stopped")

    def collect_once(self, experiment_id: str, run_id: str) -> list:
        """Collect a single snapshot — useful for testing"""
        return self._collect_snapshot(experiment_id, run_id)

    def _collect_snapshot(
        self, experiment_id: str, run_id: str
    ) -> list:
        snapshot_time = time.time()
        docs = []

        for service, queries in SERVICE_METRIC_QUERIES.items():
            metrics = {}

            for metric_name, promql in queries.items():
                try:
                    value = self._query_prometheus_scalar(promql, snapshot_time)
                    metrics[metric_name] = value
                except Exception as e:
                    metrics[metric_name] = None

            docs.append({
                "experiment_id": experiment_id,
                "run_id": run_id,
                "service": service,
                "timestamp_epoch": snapshot_time,
                "timestamp_utc": time.strftime(
                    '%Y-%m-%dT%H:%M:%SZ', time.gmtime(snapshot_time)
                ),
                "metrics": metrics,
                "collection_source": "prometheus_snapshot"
            })

        return docs

    def _query_prometheus_scalar(
        self, query: str, timestamp: float
    ) -> Optional[float]:
        """Query Prometheus and return first scalar result"""
        resp = requests.get(
            f"{self.prom_url}/api/v1/query",
            params={"query": query, "time": timestamp},
            timeout=5
        )
        resp.raise_for_status()
        data = resp.json()

        if data["status"] != "success":
            return None

        results = data["data"]["result"]
        if not results:
            return None

        # Take first result value
        value = float(results[0]["value"][1])

        # Handle NaN and Inf
        if value != value or value == float('inf'):
            return None

        return round(value, 4)


def label_time_windows(
    mongo_uri: str,
    run_id: str,
    t_inject: float,
    t_rollback: float
):
    """
    Label every metrics snapshot with its time window.
    Call this after experiment completes.
    """
    db = MongoClient(mongo_uri)["platform_db"]
    pre_start = t_inject - 300

    # PRE_FAULT
    db["metrics_snapshots"].update_many(
        {
            "run_id": run_id,
            "timestamp_epoch": {"$gte": pre_start, "$lt": t_inject}
        },
        {"$set": {"time_window": "pre_fault"}}
    )

    # FAULT_ACTIVE
    db["metrics_snapshots"].update_many(
        {
            "run_id": run_id,
            "timestamp_epoch": {"$gte": t_inject, "$lt": t_rollback}
        },
        {"$set": {"time_window": "fault_active"}}
    )

    # RECOVERY
    db["metrics_snapshots"].update_many(
        {
            "run_id": run_id,
            "timestamp_epoch": {"$gte": t_rollback}
        },
        {"$set": {"time_window": "recovery"}}
    )

    print(f"[METRICS] Time windows labeled for run {run_id}")


if __name__ == "__main__":
    # Quick test — collect one snapshot
    collector = MetricsSnapshotCollector()
    snapshots = collector.collect_once("test_exp", "test_run")
    for s in snapshots:
        print(f"\nService: {s['service']}")
        for k, v in s['metrics'].items():
            print(f"  {k}: {v}")