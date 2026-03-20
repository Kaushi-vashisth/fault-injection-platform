import time
from pymongo import MongoClient

ALERT_LEVELS = {
    "INFO":     0,
    "WARNING":  1,
    "CRITICAL": 2
}

class AlertManager:

    def __init__(self, mongo_uri: str = "mongodb://localhost:27017/"):
        self.db = MongoClient(mongo_uri)["platform_db"]
        self.collection = self.db["alerts"]

    def create_alert(
        self,
        run_id: str,
        experiment_id: str,
        alert_type: str,
        level: str,
        service: str,
        message: str,
        details: dict = None
    ) -> dict:
        alert = {
            "run_id":        run_id,
            "experiment_id": experiment_id,
            "alert_type":    alert_type,
            "level":         level,
            "service":       service,
            "message":       message,
            "details":       details or {},
            "timestamp":     time.time(),
            "timestamp_utc": time.strftime(
                '%Y-%m-%dT%H:%M:%SZ', time.gmtime()
            ),
            "acknowledged":  False
        }
        self.collection.insert_one(alert)
        print(f"[ALERT] {level} — {service}: {message}")
        return alert

    def get_active_alerts(self, run_id: str = None) -> list:
        query = {"acknowledged": False}
        if run_id:
            query["run_id"] = run_id
        return list(
            self.collection.find(query, {"_id": 0})
            .sort("timestamp", -1)
            .limit(50)
        )

    def get_all_alerts(self, run_id: str = None) -> list:
        query = {}
        if run_id:
            query["run_id"] = run_id
        return list(
            self.collection.find(query, {"_id": 0})
            .sort("timestamp", -1)
            .limit(100)
        )

    def acknowledge_alert(self, run_id: str, alert_type: str):
        self.collection.update_many(
            {"run_id": run_id, "alert_type": alert_type},
            {"$set": {"acknowledged": True}}
        )

    def clear_alerts(self, run_id: str):
        self.collection.delete_many({"run_id": run_id})
        