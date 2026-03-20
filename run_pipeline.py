import time
import threading
from pymongo import MongoClient
from fault_engine.experiment_controller import ExperimentController
from observability.metrics_collector import MetricsSnapshotCollector, label_time_windows
from observability.data_cleaner import ObservabilityDataCleaner
from analytics.spark_jobs.ingestion import load_metrics, get_baseline_stats
from analytics.spark_jobs.mttr import compute_mttr, compute_fault_window_stats, save_mttr_results
from analytics.spark_jobs.degradation import (
    compute_latency_degradation, compute_throughput_drop,
    compute_error_rate_delta, save_degradation_results
)
from analytics.spark_jobs.propagation import (
    detect_propagation, build_propagation_graph,
    compute_blast_radius, save_propagation_results
)
from scoring.resilience_scorer import ResilienceScorer


def run_full_pipeline(config_path: str):
    print("\n" + "="*60)
    print("FULL PIPELINE STARTING")
    print("="*60)

    # ── Step 1: Pre-generate IDs ──────────────────────────────────
    import uuid, yaml
    with open(config_path) as f:
        config = yaml.safe_load(f)
    experiment_id = config["experiment_id"]
    run_id = str(uuid.uuid4())

    print(f"Experiment ID: {experiment_id}")
    print(f"Run ID:        {run_id}")

    # ── Step 2: Start continuous metrics collection ───────────────
    print("\n[STEP 2] Starting continuous metrics collection...")
    collector = MetricsSnapshotCollector(interval_sec=5)
    metrics_thread = threading.Thread(
        target=collector.start,
        args=(experiment_id, run_id),
        daemon=True
    )
    metrics_thread.start()
    print("[METRICS] Background collection started")

    # ── Step 3: Run Experiment ────────────────────────────────────
    print("\n[STEP 3] Running fault injection experiment...")

    # Patch controller to use our pre-generated run_id
    from fault_engine.experiment_controller import ExperimentController
    controller = ExperimentController()

    # Override run_experiment to inject our run_id
    import yaml as _yaml
    cfg = controller._load_config(config_path)
    cfg_run_id = run_id

    # Register experiment manually
    controller.logger.log_experiment_run({
        "experiment_id": experiment_id,
        "run_id": run_id,
        "config": cfg,
        "status": "started",
        "started_at": time.time()
    })

    # Execute run directly
    controller.watchdog.start()
    result = controller._execute_single_run(cfg, run_id, 0)
    controller.watchdog.stop()

    controller.logger.update_experiment_run(run_id, {
        "status": "completed",
        "completed_at": time.time(),
        "results": [result]
    })

    print(f"Experiment complete: {result['status']}")

    # ── Step 4: Stop metrics collection ──────────────────────────
    print("\n[STEP 4] Stopping metrics collection...")
    collector.stop()
    time.sleep(3)  # Let final snapshots flush

    # ── Step 5: Label Time Windows ────────────────────────────────
    print("\n[STEP 5] Labeling time windows...")
    db = MongoClient("mongodb://localhost:27017/")["platform_db"]
    fault_event = db["fault_events"].find_one({"run_id": run_id})

    if fault_event:
        t_inject   = fault_event.get("injected_at", 0)
        t_rollback = fault_event.get("rolled_back_at", 0)
        if t_inject and t_rollback:
            label_time_windows(
                "mongodb://localhost:27017/",
                run_id, t_inject, t_rollback
            )

    # Check how many snapshots we collected
    count = db["metrics_snapshots"].count_documents({"run_id": run_id})
    print(f"[METRICS] Total snapshots collected: {count}")

    # ── Step 6: Clean Data ────────────────────────────────────────
    print("\n[STEP 6] Cleaning data...")
    cleaner = ObservabilityDataCleaner()
    cleaner.clean_experiment(run_id)

    # ── Step 7: Analytics ─────────────────────────────────────────
    print("\n[STEP 7] Running analytics...")
    metrics        = load_metrics(run_id)
    baseline_stats = get_baseline_stats(run_id)

    print(f"Baseline stats computed: {list(baseline_stats.keys())}")

    mttr         = compute_mttr(metrics, run_id, baseline_stats)
    window_stats = compute_fault_window_stats(metrics, run_id)
    save_mttr_results(run_id, experiment_id, mttr, window_stats)

    latency = compute_latency_degradation(metrics, run_id, baseline_stats)
    tput    = compute_throughput_drop(metrics, run_id, baseline_stats)
    errors  = compute_error_rate_delta(metrics, run_id)
    save_degradation_results(run_id, experiment_id, latency, tput, errors)

    fault_target = fault_event.get("target_service", "service_b") \
        if fault_event else "service_b"
    propagation  = detect_propagation(
        metrics, run_id, baseline_stats, fault_target
    )
    graph        = build_propagation_graph(propagation, fault_target)
    blast_radius = compute_blast_radius(propagation)
    save_propagation_results(
        run_id, experiment_id, propagation, graph, blast_radius
    )

    # ── Step 8: Resilience Score ──────────────────────────────────
    print("\n[STEP 8] Computing resilience score...")
    scorer = ResilienceScorer()
    score  = scorer.compute_score(run_id)

    # ── Final Summary ─────────────────────────────────────────────
    print("\n" + "="*60)
    print("PIPELINE COMPLETE")
    print("="*60)
    print(f"Experiment ID:      {experiment_id}")
    print(f"Run ID:             {run_id}")
    print(f"Snapshots collected:{count}")
    print(f"Resilience Score:   {score.get('final_resilience_score')}")
    print(f"Interpretation:     {score.get('score_interpretation')}")
    print(f"Component Scores:   {score.get('component_scores')}")
    print("="*60)
    return score


if __name__ == "__main__":
    import sys
    config = sys.argv[1] if len(sys.argv) > 1 else \
        "experiments/configs/exp_001_cpu_service_b.yaml"
    run_full_pipeline(config)