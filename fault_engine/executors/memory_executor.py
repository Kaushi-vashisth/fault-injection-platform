import subprocess
import shlex
from dataclasses import dataclass

@dataclass
class MemoryFaultParams:
    target_container: str
    vm_workers: int
    vm_bytes_mb: int
    duration_sec: int
    fault_id: str
    experiment_id: str

class MemoryFaultExecutor:

    def inject(self, params: MemoryFaultParams) -> dict:
        total_mb = params.vm_workers * params.vm_bytes_mb

        cmd = (
            f"docker exec -d {params.target_container} "
            f"stress-ng --vm {params.vm_workers} "
            f"--vm-bytes {params.vm_bytes_mb}M "
            f"--vm-keep "
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
                f"Memory injection failed on {params.target_container}: {result.stderr}"
            )

        print(f"[MEMORY] Injected on {params.target_container} — "
              f"{params.vm_workers} workers x {params.vm_bytes_mb}MB "
              f"= {total_mb}MB total for {params.duration_sec}s")

        return {
            "status": "injected",
            "fault_id": params.fault_id,
            "target": params.target_container,
            "total_allocated_mb": total_mb
        }

    def rollback(self, params: MemoryFaultParams) -> dict:
        cmd = f"docker exec {params.target_container} pkill -f stress-ng"
        result = subprocess.run(
            shlex.split(cmd),
            capture_output=True,
            text=True,
            timeout=10
        )
        success = result.returncode in [0, 1]
        print(f"[MEMORY] Rollback on {params.target_container} — "
              f"{'success' if success else 'failed'}")
        return {
            "status": "rolled_back" if success else "rollback_failed",
            "fault_id": params.fault_id
        }

    def verify(self, params: MemoryFaultParams) -> bool:
        """Check stress-ng memory worker is running"""
        cmd = f"docker exec {params.target_container} pgrep -f stress-ng"
        result = subprocess.run(
            shlex.split(cmd),
            capture_output=True,
            text=True
        )
        return result.returncode == 0