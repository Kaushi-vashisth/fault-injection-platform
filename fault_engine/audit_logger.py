import time
from pymongo import MongoClient
from pymongo.database import Database
from typing import Optional

class AuditLogger:

    def __init__(self, mongo_uri: str = "mongodb://localhost:27017/"):
        self.client = MongoClient(mongo_uri)
        self.db = self.client["platform_db"]
        self.fault_events = self.db["fault_events"]
        self.phases = self.db["experiment_phases"]

    def log_fault_event(self, event: dict) -> str:
        """Log a fault injection event to MongoDB"""
        event["logged_at"] = time.time()
        result = self.fault_events.insert_one(event)
        print(f"[AUDIT] Fault event logged: {event.get('fault_id')}")
        return str(result.inserted_id)

    def update_fault_event(self, fault_id: str, update: dict):
        """Update an existing fault event (e.g. add rollback info)"""
        self.fault_events.update_one(
            {"fault_id": fault_id},
            {"$set": update}
        )
        print(f"[AUDIT] Fault event updated: {fault_id}")

    def log_phase(
        self,
        fault_id: str,
        phase: str,
        status: str,
        extra: Optional[dict] = None
    ):
        """Log experiment phase transitions"""
        doc = {
            "fault_id": fault_id,
            "phase": phase,
            "status": status,
            "timestamp": time.time()
        }
        if extra:
            doc.update(extra)
        self.phases.insert_one(doc)
        print(f"[AUDIT] Phase: {phase} → {status}")

    def log_experiment_run(self, experiment_doc: dict) -> str:
        """Register a new experiment run"""
        experiment_doc["created_at"] = time.time()
        result = self.db["experiment_runs"].insert_one(experiment_doc)
        print(f"[AUDIT] Experiment run logged: "
              f"{experiment_doc.get('experiment_id')}")
        return str(result.inserted_id)

    def update_experiment_run(self, run_id: str, update: dict):
        """Update experiment run status"""
        self.db["experiment_runs"].update_one(
            {"run_id": run_id},
            {"$set": update}
        )

    def get_experiment_runs(self, experiment_id: str) -> list:
        """Retrieve all runs for an experiment"""
        return list(
            self.db["experiment_runs"].find(
                {"experiment_id": experiment_id},
                {"_id": 0}
            )
        )