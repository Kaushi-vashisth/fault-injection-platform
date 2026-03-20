import subprocess
import shlex
import time
from dataclasses import dataclass
from enum import Enum
from typing import Optional
import requests

class CrashMode(Enum):
    SIGKILL = "SIGKILL"
    SIGTERM = "SIGTERM"

@dataclass
class CrashFaultParams:
    target_container: str
    crash_mode: CrashMode
    recovery_delay_sec: int
    auto_restart: bool
    fault_id: str
    experiment_id: str
    duration_sec: int = 0

SERVICE_PORTS = {
    "service_a": 8000,
    "service_b": 8001,
    "service_c": 8002
}

class CrashFaultExecutor:

    def inject(self, params: CrashFaultParams) -> dict:
        inject_time = time.time()

        cmd = (
            f"docker kill --signal={params.crash_mode.value} "
            f"{params.target_container}"
        )
        result = subprocess.run(
            shlex.split(cmd),
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"Crash injection failed on {params.target_container}: "
                f"{result.stderr}"
            )

        print(f"[CRASH] {params.crash_mode.value} sent to "
              f"{params.target_container}")

        return {
            "status": "crashed",
            "fault_id": params.fault_id,
            "target": params.target_container,
            "crash_mode": params.crash_mode.value,
            "crash_time": inject_time
        }

    def rollback(self, params: CrashFaultParams) -> dict:
        """Restart the container after recovery delay"""
        print(f"[CRASH] Waiting {params.recovery_delay_sec}s before restart...")
        time.sleep(params.recovery_delay_sec)

        # Check if auto-restarted already
        status = self._get_container_status(params.target_container)
        if status == "running":
            print(f"[CRASH] {params.target_container} auto-recovered")
            return {
                "status": "auto_recovered",
                "fault_id": params.fault_id
            }

        # Manual restart
        cmd = f"docker start {params.target_container}"
        result = subprocess.run(
            shlex.split(cmd),
            capture_output=True,
            text=True,
            timeout=30
        )
        success = result.returncode == 0
        print(f"[CRASH] Manual restart of {params.target_container} — "
              f"{'success' if success else 'failed'}")

        return {
            "status": "restarted" if success else "restart_failed",
            "fault_id": params.fault_id
        }

    def wait_for_recovery(
        self,
        params: CrashFaultParams,
        timeout_sec: int = 120
    ) -> dict:
        """Poll until service is healthy again"""
        start = time.time()
        port = SERVICE_PORTS.get(params.target_container, 8000)

        print(f"[CRASH] Waiting for {params.target_container} to recover...")

        while time.time() - start < timeout_sec:
            if self._is_healthy(params.target_container, port):
                recovery_time = time.time() - start
                print(f"[CRASH] {params.target_container} recovered "
                      f"in {round(recovery_time, 1)}s")
                return {
                    "recovered": True,
                    "recovery_time_sec": round(recovery_time, 1),
                    "fault_id": params.fault_id
                }
            time.sleep(2)

        print(f"[CRASH] {params.target_container} did not recover "
              f"within {timeout_sec}s")
        return {
            "recovered": False,
            "recovery_time_sec": timeout_sec,
            "fault_id": params.fault_id
        }

    def _get_container_status(self, container: str) -> str:
        cmd = f"docker inspect -f {{{{.State.Status}}}} {container}"
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True
        )
        return result.stdout.strip()

    def _is_healthy(self, container: str, port: int) -> bool:
        try:
            resp = requests.get(
                f"http://localhost:{port}/health",
                timeout=2
            )
            return resp.status_code == 200
        except Exception:
            return False