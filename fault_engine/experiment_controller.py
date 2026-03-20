import yaml
import uuid
import time
import signal
import sys
from pymongo import MongoClient
from fault_engine.executors.cpu_executor import CPUFaultExecutor, CPUFaultParams
from fault_engine.executors.memory_executor import MemoryFaultExecutor, MemoryFaultParams
from fault_engine.executors.network_executor import NetworkFaultExecutor, NetworkFaultParams
from fault_engine.executors.crash_executor import CrashFaultExecutor, CrashFaultParams, CrashMode
from fault_engine.audit_logger import AuditLogger
from fault_engine.watchdog import FaultWatchdog

class ExperimentController:

    def __init__(self, mongo_uri: str = "mongodb://localhost:27017/"):
        self.mongo = MongoClient(mongo_uri)
        self.db = self.mongo["platform_db"]
        self.logger = AuditLogger(mongo_uri)
        self.active_faults = {}
        self.executors = {
            "cpu":     CPUFaultExecutor(),
            "memory":  MemoryFaultExecutor(),
            "network": NetworkFaultExecutor(),
            "crash":   CrashFaultExecutor()
        }
        self.watchdog = FaultWatchdog(self.active_faults)
        self._register_signal_handlers()

    def run_experiment(self, config_path: str) -> dict:
        """Full experiment lifecycle"""
        config = self._load_config(config_path)
        run_id = str(uuid.uuid4())

        print(f"\n{'='*60}")
        print(f"EXPERIMENT: {config['experiment_id']}")
        print(f"RUN ID:     {run_id}")
        print(f"{'='*60}")

        # Register in MongoDB
        self.logger.log_experiment_run({
            "experiment_id": config["experiment_id"],
            "run_id": run_id,
            "config": config,
            "status": "started",
            "started_at": time.time()
        })

        # Start watchdog
        self.watchdog.start()

        results = []
        repeat = config.get("repeat", 1)

        for run_number in range(repeat):
            print(f"\n--- Run {run_number + 1}/{repeat} ---")
            result = self._execute_single_run(config, run_id, run_number)
            results.append(result)

            # Cooldown between runs
            if run_number < repeat - 1:
                cooldown = config.get("inter_run_cooldown_sec", 60)
                print(f"Cooldown: {cooldown}s")
                time.sleep(cooldown)

        # Stop watchdog
        self.watchdog.stop()

        # Final update
        self.logger.update_experiment_run(run_id, {
            "status": "completed",
            "completed_at": time.time(),
            "results": results
        })

        print(f"\n{'='*60}")
        print(f"EXPERIMENT COMPLETED: {config['experiment_id']}")
        print(f"{'='*60}\n")

        return {
            "experiment_id": config["experiment_id"],
            "run_id": run_id,
            "runs": results
        }

    def _execute_single_run(
        self, config: dict, run_id: str, run_number: int
    ) -> dict:
        fault_config = config["fault"]
        fault_id = f"{run_id}_run{run_number}"
        phases = {}

        try:
            # ── Phase 1: Warmup ──────────────────────────────────
            warmup = config.get("warmup_sec", 30)
            print(f"[{self._now()}] WARMUP ({warmup}s)...")
            self.logger.log_phase(fault_id, "warmup", "started")
            time.sleep(warmup)
            phases["warmup_completed_at"] = time.time()

            # ── Phase 2: Baseline ────────────────────────────────
            baseline = config.get("baseline_sec", 60)
            print(f"[{self._now()}] BASELINE ({baseline}s)...")
            self.logger.log_phase(fault_id, "baseline", "started")
            time.sleep(baseline)
            phases["baseline_completed_at"] = time.time()

            # ── Phase 3: Inject ──────────────────────────────────
            print(f"[{self._now()}] INJECTING FAULT: {fault_config['type']} "
                  f"→ {fault_config['target']}")
            self.logger.log_phase(fault_id, "injection", "started")

            params = self._build_params(fault_config, fault_id, run_id)
            executor = self.executors[fault_config["type"]]
            inject_result = executor.inject(params)

            inject_time = time.time()
            phases["injected_at"] = inject_time
            self.active_faults[fault_id] = (executor, params)
            self.watchdog.register_fault(
                fault_id,
                fault_config["params"].get("duration_sec", 60)
            )

            # Log to MongoDB
            self.logger.log_fault_event({
                "fault_id": fault_id,
                "run_id": run_id,
                "experiment_id": config["experiment_id"],
                "run_number": run_number,
                "fault_type": fault_config["type"],
                "target_service": fault_config["target"],
                "parameters": fault_config["params"],
                "injected_at": inject_time,
                "inject_result": inject_result,
                "status": "active"
            })

            # ── Phase 4: Active fault window ─────────────────────
            duration = fault_config["params"].get("duration_sec", 60)
            print(f"[{self._now()}] FAULT ACTIVE for {duration}s...")
            time.sleep(duration)

            # ── Phase 5: Rollback ────────────────────────────────
            print(f"[{self._now()}] ROLLING BACK...")
            rollback_result = executor.rollback(params)
            rollback_time = time.time()
            phases["rolled_back_at"] = rollback_time

            if fault_id in self.active_faults:
                del self.active_faults[fault_id]
            self.watchdog.deregister_fault(fault_id)

            self.logger.update_fault_event(fault_id, {
                "status": "rolled_back",
                "rolled_back_at": rollback_time,
                "rollback_result": rollback_result
            })

            # ── Phase 6: Recovery window ─────────────────────────
            recovery = config.get("recovery_window_sec", 60)
            print(f"[{self._now()}] RECOVERY WINDOW ({recovery}s)...")
            self.logger.log_phase(fault_id, "recovery", "started")
            time.sleep(recovery)
            phases["recovery_end"] = time.time()

            print(f"[{self._now()}] RUN {run_number + 1} COMPLETE ✓")

            return {
                "run_number": run_number,
                "fault_id": fault_id,
                "status": "completed",
                "phases": phases
            }

        except Exception as e:
            print(f"ERROR in run {run_number}: {e}")
            self._emergency_rollback_all()
            return {
                "run_number": run_number,
                "fault_id": fault_id,
                "status": "failed",
                "error": str(e),
                "phases": phases
            }

    def _emergency_rollback_all(self):
        """Roll back all active faults immediately"""
        print("\n⚠ EMERGENCY ROLLBACK — rolling back all active faults")
        for fault_id, (executor, params) in list(self.active_faults.items()):
            try:
                executor.rollback(params)
                print(f"  Rolled back: {fault_id}")
            except Exception as e:
                print(f"  Rollback failed for {fault_id}: {e}")
        self.active_faults.clear()

    def _register_signal_handlers(self):
        """Handle Ctrl+C and SIGTERM gracefully"""
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def _signal_handler(self, signum, frame):
        print(f"\nSignal {signum} received — emergency rollback")
        self._emergency_rollback_all()
        self.watchdog.stop()
        sys.exit(0)

    def _build_params(self, fault_config: dict, fault_id: str, run_id: str):
        """Build typed params object from YAML config"""
        t = fault_config["type"]
        p = fault_config["params"]
        target = fault_config["target"]

        if t == "cpu":
            return CPUFaultParams(
                target_container=target,
                cpu_workers=p["cpu_workers"],
                load_percent=p["load_percent"],
                duration_sec=p["duration_sec"],
                fault_id=fault_id,
                experiment_id=run_id
            )
        elif t == "memory":
            return MemoryFaultParams(
                target_container=target,
                vm_workers=p["vm_workers"],
                vm_bytes_mb=p["vm_bytes_mb"],
                duration_sec=p["duration_sec"],
                fault_id=fault_id,
                experiment_id=run_id
            )
        elif t == "network":
            return NetworkFaultParams(
                target_container=target,
                delay_ms=p["delay_ms"],
                jitter_ms=p["jitter_ms"],
                loss_percent=p["loss_percent"],
                duration_sec=p["duration_sec"],
                fault_id=fault_id,
                experiment_id=run_id
            )
        elif t == "crash":
            return CrashFaultParams(
                target_container=target,
                crash_mode=CrashMode[p.get("crash_mode", "SIGKILL")],
                recovery_delay_sec=p.get("recovery_delay_sec", 5),
                auto_restart=p.get("auto_restart", True),
                duration_sec=p.get("duration_sec", 0),
                fault_id=fault_id,
                experiment_id=run_id
            )
        else:
            raise ValueError(f"Unknown fault type: {t}")

    def _load_config(self, path: str) -> dict:
        with open(path) as f:
            return yaml.safe_load(f)

    def _now(self) -> str:
        return time.strftime('%H:%M:%S')


# ── Entry point ───────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True, help="Path to experiment YAML")
    args = parser.parse_args()

    controller = ExperimentController()
    result = controller.run_experiment(args.config)
    print(result)