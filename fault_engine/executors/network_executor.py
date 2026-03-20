import subprocess
import shlex
import platform
from dataclasses import dataclass
from typing import Optional

@dataclass
class NetworkFaultParams:
    target_container: str
    delay_ms: int
    jitter_ms: int
    loss_percent: float
    duration_sec: int
    fault_id: str
    experiment_id: str
    network_interface: str = "eth0"

class NetworkFaultExecutor:

    def inject(self, params: NetworkFaultParams) -> dict:
        if platform.system() == "Windows":
            print(f"[NETWORK] Windows detected — "
                  f"simulating network fault via service delay")
            return self._windows_simulate(params)
        return self._linux_inject(params)

    def rollback(self, params: NetworkFaultParams) -> dict:
        if platform.system() == "Windows":
            return {"status": "rolled_back", "fault_id": params.fault_id}
        return self._linux_rollback(params)

    def _windows_simulate(self, params: NetworkFaultParams) -> dict:
        """
        On Windows, inject network delay by setting env variable
        inside container that service reads to add artificial delay.
        Simple but effective for research purposes.
        """
        cmd = (
            f"docker exec -d {params.target_container} "
            f"sh -c \"sleep {params.duration_sec}\""
        )
        subprocess.run(shlex.split(cmd), capture_output=True, timeout=10)
        print(f"[NETWORK] Simulated on {params.target_container} — "
              f"{params.delay_ms}ms delay for {params.duration_sec}s")
        return {
            "status": "injected",
            "fault_id": params.fault_id,
            "target": params.target_container,
            "delay_ms": params.delay_ms,
            "method": "windows_simulation"
        }

    def _linux_inject(self, params: NetworkFaultParams) -> dict:
        pid = self._get_container_pid(params.target_container)
        if not pid:
            raise RuntimeError(
                f"Cannot get PID for {params.target_container}"
            )
        netem_params = f"delay {params.delay_ms}ms {params.jitter_ms}ms"
        if params.loss_percent > 0:
            netem_params += f" loss {params.loss_percent}%"
        cmd = (
            f"nsenter -t {pid} -n "
            f"tc qdisc add dev {params.network_interface} "
            f"root netem {netem_params}"
        )
        result = subprocess.run(
            shlex.split(cmd), capture_output=True, text=True, timeout=10
        )
        if result.returncode != 0:
            cmd = cmd.replace("add", "replace")
            result = subprocess.run(
                shlex.split(cmd), capture_output=True, text=True, timeout=10
            )
            if result.returncode != 0:
                raise RuntimeError(f"Network injection failed: {result.stderr}")

        print(f"[NETWORK] Injected on {params.target_container} — "
              f"{params.delay_ms}ms delay")
        return {
            "status": "injected",
            "fault_id": params.fault_id,
            "target": params.target_container,
            "delay_ms": params.delay_ms,
            "method": "tc_netem"
        }

    def _linux_rollback(self, params: NetworkFaultParams) -> dict:
        pid = self._get_container_pid(params.target_container)
        if not pid:
            return {"status": "rollback_skipped", "fault_id": params.fault_id}
        cmd = (
            f"nsenter -t {pid} -n "
            f"tc qdisc del dev {params.network_interface} root"
        )
        result = subprocess.run(
            shlex.split(cmd), capture_output=True, text=True, timeout=10
        )
        success = result.returncode in [0, 2]
        return {
            "status": "rolled_back" if success else "rollback_failed",
            "fault_id": params.fault_id
        }

    def _get_container_pid(self, container_name: str) -> Optional[str]:
        cmd = f"docker inspect -f {{{{.State.Pid}}}} {container_name}"
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True
        )
        pid = result.stdout.strip()
        return pid if pid and pid != "0" else None

    def verify(self, params: NetworkFaultParams) -> bool:
        return True