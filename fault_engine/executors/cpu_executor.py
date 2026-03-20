import subprocess
import shlex
from dataclasses import dataclass
from typing import Optional

@dataclass
class CPUFaultParams:
    target_container: str
    cpu_workers: int
    load_percent: int
    duration_sec: int
    fault_id: str
    experiment_id: str

class CPUFaultExecutor:

    def inject(self, params: CPUFaultParams) -> dict:
        cmd = (
            f"docker exec -d {params.target_container} "
            f"stress-ng --cpu {params.cpu_workers} "
            f"--cpu-load {params.load_percent} "
            f"--timeout {params.duration_sec}s"
        )
        result = subprocess.run(
            shlex.split(cmd),
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"CPU injection failed on {params.target_container}: {result.stderr}"
            )
        print(f"[CPU] Injected on {params.target_container} — "
              f"{params.cpu_workers} workers at {params.load_percent}% for {params.duration_sec}s")
        return {
            "status": "injected",
            "fault_id": params.fault_id,
            "target": params.target_container,
            "workers": params.cpu_workers,
            "load_percent": params.load_percent
        }

    def rollback(self, params: CPUFaultParams) -> dict:
        cmd = f"docker exec {params.target_container} pkill -f stress-ng"
        result = subprocess.run(
            shlex.split(cmd),
            capture_output=True,
            text=True,
            timeout=10
        )
        # pkill returns 1 if no process found — that's fine (already stopped)
        success = result.returncode in [0, 1]
        print(f"[CPU] Rollback on {params.target_container} — "
              f"{'success' if success else 'failed'}")
        return {
            "status": "rolled_back" if success else "rollback_failed",
            "fault_id": params.fault_id
        }

    def verify(self, params: CPUFaultParams) -> bool:
        """Check stress-ng is actually running in the container"""
        cmd = f"docker exec {params.target_container} pgrep -f stress-ng"
        result = subprocess.run(
            shlex.split(cmd),
            capture_output=True,
            text=True
        )
        return result.returncode == 0