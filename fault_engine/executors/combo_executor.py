import time
from dataclasses import dataclass, field
from typing import List
from enum import Enum

from fault_engine.executors.cpu_executor import CPUFaultExecutor, CPUFaultParams
from fault_engine.executors.memory_executor import MemoryFaultExecutor, MemoryFaultParams
from fault_engine.executors.network_executor import NetworkFaultExecutor, NetworkFaultParams
from fault_engine.executors.crash_executor import CrashFaultExecutor, CrashFaultParams, CrashMode

class CompositionMode(Enum):
    CONCURRENT  = "concurrent"
    SEQUENTIAL  = "sequential"
    OVERLAPPING = "overlapping"

@dataclass
class FaultComposition:
    experiment_id: str
    composition_mode: CompositionMode
    faults: List[dict]
    offset_sec: float = 10.0

class CombinationFaultExecutor:

    def __init__(self):
        self.executors = {
            "cpu":     CPUFaultExecutor(),
            "memory":  MemoryFaultExecutor(),
            "network": NetworkFaultExecutor(),
            "crash":   CrashFaultExecutor()
        }

    def inject_combination(self, composition: FaultComposition) -> dict:
        results = []

        if composition.composition_mode == CompositionMode.CONCURRENT:
            # Start all faults at the same time
            for fault in composition.faults:
                try:
                    executor = self.executors[fault["type"]]
                    result = executor.inject(fault["params"])
                    results.append(result)
                except Exception as e:
                    results.append({
                        "status": "failed",
                        "error": str(e),
                        "fault_type": fault["type"]
                    })

        elif composition.composition_mode == CompositionMode.SEQUENTIAL:
            # Each fault runs fully before the next starts
            for fault in composition.faults:
                try:
                    executor = self.executors[fault["type"]]
                    result = executor.inject(fault["params"])
                    results.append(result)
                    # Wait for this fault to finish
                    time.sleep(fault["params"].duration_sec)
                    executor.rollback(fault["params"])
                except Exception as e:
                    results.append({
                        "status": "failed",
                        "error": str(e),
                        "fault_type": fault["type"]
                    })

        elif composition.composition_mode == CompositionMode.OVERLAPPING:
            # Each fault starts offset_sec after the previous
            for i, fault in enumerate(composition.faults):
                if i > 0:
                    time.sleep(composition.offset_sec)
                try:
                    executor = self.executors[fault["type"]]
                    result = executor.inject(fault["params"])
                    results.append(result)
                except Exception as e:
                    results.append({
                        "status": "failed",
                        "error": str(e),
                        "fault_type": fault["type"]
                    })

        print(f"[COMBO] {composition.composition_mode.value} — "
              f"{len(composition.faults)} faults injected")

        return {
            "experiment_id": composition.experiment_id,
            "composition_mode": composition.composition_mode.value,
            "fault_count": len(composition.faults),
            "results": results
        }

    def rollback_all(self, composition: FaultComposition) -> None:
        """Emergency rollback — roll back all faults"""
        print("[COMBO] Rolling back all faults...")
        for fault in composition.faults:
            try:
                executor = self.executors[fault["type"]]
                executor.rollback(fault["params"])
            except Exception as e:
                print(f"[COMBO] Rollback failed for {fault['type']}: {e}")