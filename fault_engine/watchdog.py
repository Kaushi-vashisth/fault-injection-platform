import threading
import time
from typing import Dict, Tuple

class FaultWatchdog:
    """
    Background thread that monitors active faults and force-rolls back
    any fault that has exceeded its TTL + grace period.
    Prevents faults from persisting indefinitely if controller crashes.
    """

    def __init__(self, active_faults: dict, grace_period_sec: int = 30):
        self.active_faults = active_faults
        self.grace_period = grace_period_sec
        self.fault_ttls: Dict[str, float] = {}
        self._stop_event = threading.Event()
        self._thread = None

    def register_fault(self, fault_id: str, duration_sec: int):
        """Register a fault with its expected expiry time"""
        expiry = time.time() + duration_sec + self.grace_period
        self.fault_ttls[fault_id] = expiry
        print(f"[WATCHDOG] Registered fault {fault_id} "
              f"— expires in {duration_sec + self.grace_period}s")

    def deregister_fault(self, fault_id: str):
        """Remove a fault that has been cleanly rolled back"""
        self.fault_ttls.pop(fault_id, None)
        print(f"[WATCHDOG] Deregistered fault {fault_id}")

    def start(self):
        """Start the watchdog background thread"""
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._watch,
            daemon=True,
            name="FaultWatchdog"
        )
        self._thread.start()
        print("[WATCHDOG] Started")

    def stop(self):
        """Stop the watchdog thread"""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=10)
        print("[WATCHDOG] Stopped")

    def _watch(self):
        """Main watchdog loop — checks every 5 seconds"""
        while not self._stop_event.is_set():
            now = time.time()

            expired = [
                fault_id
                for fault_id, expiry in list(self.fault_ttls.items())
                if now > expiry and fault_id in self.active_faults
            ]

            for fault_id in expired:
                print(f"[WATCHDOG] ⚠ Force rolling back expired fault: "
                      f"{fault_id}")
                try:
                    executor, params = self.active_faults[fault_id]
                    executor.rollback(params)
                    del self.active_faults[fault_id]
                    del self.fault_ttls[fault_id]
                    print(f"[WATCHDOG] Force rollback complete: {fault_id}")
                except Exception as e:
                    print(f"[WATCHDOG] Force rollback failed for "
                          f"{fault_id}: {e}")

            self._stop_event.wait(timeout=5)