"""
Real-Time Fault Detection Pipeline
Replaces run_pipeline.py with live detection capability.

Pipeline:
1. Start metrics collection (background thread)
2. Start real-time detector (background thread)
3. Run experiment
4. Detector fires alerts as anomalies are detected
5. After experiment: run full analytics + scoring
"""
import time
import threading
import uuid
import yaml
from pymongo import MongoClient

from fault_engine.experiment_controller import ExperimentController
from observability.metrics_collector import (
    MetricsSnapshotCollector, label_time_windows
)
from observability.data_cleaner import ObservabilityDataCleaner
from analytics.spark_jobs.ingestion import load_metrics, get_baseline_stats
from analytics.spark_jobs.mttr import (
    compute_mttr, compute_fault_window_stats, save_mttr_results
)
from analytics.spark_jobs.degradation import (
    compute_latency_degradation, compute_throughput_drop,
    compute_error_rate_delta, save_degradation_results
)
from analytics.spark_jobs.propagation import (
    detect_propagation, build_propagation_graph,
    compute_blast_radius, save_propagation_results
)
from scoring.resilience_scorer import ResilienceScorer
from realtime.detector import RealTimeDetector
from realtime.alert_manager import AlertManager


def run_realtime_pipeline(config_path: str) -> dict:
    print("\n" + "="*60)
    print("REAL-TIME FAULT DETECTION PIPELINE")
    print("="*60)

    # ── Load config ───────────────────────────────────────────────
    with open(config_path) as f:
        config = yaml.safe_load(f)

    experiment_id = config["experiment_id"]
    run_id        = str(uuid.uuid4())

    print(f"Experiment: {experiment_id}")
    print(f"Run ID:     {run_id}")

    db            = MongoClient("mongodb://localhost:27017/")["platform_db"]
    alert_manager = AlertManager()

    # ── Step 1: Register experiment ───────────────────────────────
    controller = ExperimentController()
    controller.logger.log_experiment_run({
        "experiment_id": experiment_id,
        "run_id":        run_id,
        "config":        config,
        "status":        "started",
        "started_at":    time.time()
    })

    # ── Step 2: Start metrics collection ─────────────────────────
    print("\n[STEP 1] Starting metrics collection...")
    collector = MetricsSnapshotCollector(interval_sec=5)
    metrics_thread = threading.Thread(
        target=collector.start,
        args=(experiment_id, run_id),
        daemon=True
    )
    metrics_thread.start()
    print("[METRICS] Collection started ✅")

    # ── Step 3: Warmup + Baseline ─────────────────────────────────
    warmup   = config.get("warmup_sec", 30)
    baseline = config.get("baseline_sec", 60)

    print(f"\n[STEP 2] Warmup ({warmup}s)...")
    time.sleep(warmup)

    print(f"\n[STEP 3] Baseline collection ({baseline}s)...")
    time.sleep(baseline)

    # Compute baseline stats from collected data
    print("\n[STEP 4] Computing baseline statistics...")
    baseline_stats = get_baseline_stats(run_id)

    if baseline_stats:
        print(f"Baseline computed for: {list(baseline_stats.keys())}")
    else:
        print("Warning: No baseline stats — using defaults")
        baseline_stats = {
            s: {
                "latency_mean": 5.0,
                "latency_std": 1.0,
                "rps_mean": 0.1,
                "latency_threshold": 7.0
            }
            for s in ["service_a", "service_b", "service_c"]
        }

    # ── Step 4: Start real-time detector ─────────────────────────
    print("\n[STEP 5] Starting real-time detector...")
    detector = RealTimeDetector(
        run_id          = run_id,
        experiment_id   = experiment_id,
        baseline_stats  = baseline_stats,
        check_interval_sec = 10
    )
    detector.start()
    print("[DETECTOR] Real-time detection active ✅")
    print("[DETECTOR] Will fire alerts if anomalies detected")

    # ── Step 5: Inject fault ──────────────────────────────────────
    print(f"\n[STEP 6] Injecting fault...")
    fault_config = config["fault"]
    fault_id     = f"{run_id}_run0"

    params   = controller._build_params(fault_config, fault_id, run_id)
    executor = controller.executors[fault_config["type"]]

    controller.watchdog.start()
    inject_result = executor.inject(params)
    inject_time   = time.time()

    controller.active_faults[fault_id] = (executor, params)
    controller.watchdog.register_fault(
        fault_id,
        fault_config["params"].get("duration_sec", 60)
    )

    controller.logger.log_fault_event({
        "fault_id":       fault_id,
        "run_id":         run_id,
        "experiment_id":  experiment_id,
        "run_number":     0,
        "fault_type":     fault_config["type"],
        "target_service": fault_config["target"],
        "parameters":     fault_config["params"],
        "injected_at":    inject_time,
        "inject_result":  inject_result,
        "status":         "active"
    })

    print(f"[FAULT] {fault_config['type']} injected on "
          f"{fault_config['target']} ✅")
    print("[DETECTOR] Monitoring for anomalies...")

    # ── Step 6: Active fault window ───────────────────────────────
    duration = fault_config["params"].get("duration_sec", 60)
    print(f"\n[STEP 7] Fault active for {duration}s...")
    print("         Watch for ALERT messages below ↓")
    time.sleep(duration)

    # ── Step 7: Rollback ──────────────────────────────────────────
    print(f"\n[STEP 8] Rolling back fault...")
    rollback_result = executor.rollback(params)
    rollback_time   = time.time()

    if fault_id in controller.active_faults:
        del controller.active_faults[fault_id]
    controller.watchdog.deregister_fault(fault_id)
    controller.watchdog.stop()

    controller.logger.update_fault_event(fault_id, {
        "status":         "rolled_back",
        "rolled_back_at": rollback_time,
        "rollback_result": rollback_result
    })

    # ── Step 8: Recovery window ───────────────────────────────────
    recovery = config.get("recovery_window_sec", 60)
    print(f"\n[STEP 9] Recovery window ({recovery}s)...")
    time.sleep(recovery)

    # ── Step 9: Stop detector + metrics ──────────────────────────
    print("\n[STEP 10] Stopping detector and metrics collection...")
    detector.stop()
    collector.stop()
    time.sleep(3)

    # ── Step 10: Label time windows ───────────────────────────────
    print("\n[STEP 11] Labeling time windows...")
    label_time_windows(
        "mongodb://localhost:27017/",
        run_id, inject_time, rollback_time
    )

    total_snapshots = db["metrics_snapshots"].count_documents(
        {"run_id": run_id}
    )
    total_alerts = db["alerts"].count_documents({"run_id": run_id})
    print(f"Snapshots collected: {total_snapshots}")
    print(f"Alerts fired:        {total_alerts}")

    # ── Step 11: Analytics ────────────────────────────────────────
    print("\n[STEP 12] Running post-experiment analytics...")
    ObservabilityDataCleaner().clean_experiment(run_id)

    metrics        = load_metrics(run_id)
    baseline_stats = get_baseline_stats(run_id)

    mttr         = compute_mttr(metrics, run_id, baseline_stats)
    window_stats = compute_fault_window_stats(metrics, run_id)
    save_mttr_results(run_id, experiment_id, mttr, window_stats)

    latency = compute_latency_degradation(
        metrics, run_id, baseline_stats
    )
    tput    = compute_throughput_drop(metrics, run_id, baseline_stats)
    errors  = compute_error_rate_delta(metrics, run_id)
    save_degradation_results(
        run_id, experiment_id, latency, tput, errors
    )

    fault_event  = db["fault_events"].find_one({"run_id": run_id})
    fault_target = fault_event.get(
        "target_service", "service_b"
    ) if fault_event else "service_b"

    propagation  = detect_propagation(
        metrics, run_id, baseline_stats, fault_target
    )
    graph        = build_propagation_graph(propagation, fault_target)
    blast_radius = compute_blast_radius(propagation)
    save_propagation_results(
        run_id, experiment_id, propagation, graph, blast_radius
    )

    # ── Step 12: Resilience score ─────────────────────────────────
    print("\n[STEP 13] Computing resilience score...")
    scorer = ResilienceScorer()
    score  = scorer.compute_score(run_id)

    # ── Step 13: Update experiment ────────────────────────────────
    controller.logger.update_experiment_run(run_id, {
        "status":       "completed",
        "completed_at": time.time()
    })

    # ── Final Summary ─────────────────────────────────────────────
    alerts = alert_manager.get_all_alerts(run_id)

    print("\n" + "="*60)
    print("REAL-TIME PIPELINE COMPLETE")
    print("="*60)
    print(f"Experiment:       {experiment_id}")
    print(f"Run ID:           {run_id}")
    print(f"Snapshots:        {total_snapshots}")
    print(f"Alerts fired:     {total_alerts}")
    print(f"Resilience Score: {score.get('final_resilience_score')}")
    print(f"Interpretation:   {score.get('score_interpretation')}")

    if alerts:
        print(f"\nAlerts Summary:")
        for alert in alerts[:5]:
            print(f"  [{alert['level']}] {alert['message']}")

    print("="*60)

    return {
        "run_id":            run_id,
        "experiment_id":     experiment_id,
        "resilience_score":  score.get("final_resilience_score"),
        "alerts_fired":      total_alerts,
        "alerts":            alerts
    }


if __name__ == "__main__":
    import sys
    config = sys.argv[1] if len(sys.argv) > 1 \
        else "experiments/configs/exp_001_cpu_service_b.yaml"
    run_realtime_pipeline(config)