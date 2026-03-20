from pymongo import MongoClient, ASCENDING, DESCENDING

def initialize_collections_and_indexes(
    mongo_uri: str = "mongodb://localhost:27017/"
):
    db = MongoClient(mongo_uri)["platform_db"]

    # ── metrics_snapshots ──────────────────────────────────────────
    db["metrics_snapshots"].create_index(
        [("experiment_id", ASCENDING),
         ("service", ASCENDING),
         ("timestamp_epoch", ASCENDING)],
        name="exp_service_time",
        background=True
    )
    db["metrics_snapshots"].create_index(
        [("timestamp_epoch", ASCENDING)],
        name="time_range",
        background=True
    )
    db["metrics_snapshots"].create_index(
        [("run_id", ASCENDING), ("time_window", ASCENDING)],
        name="run_window",
        background=True
    )

    # ── log_entries ────────────────────────────────────────────────
    db["log_entries"].create_index(
        [("experiment_id", ASCENDING),
         ("service", ASCENDING),
         ("timestamp_epoch", ASCENDING)],
        name="exp_service_time",
        background=True
    )
    db["log_entries"].create_index(
        [("level", ASCENDING),
         ("timestamp_epoch", DESCENDING)],
        name="error_log_lookup",
        background=True
    )
    db["log_entries"].create_index(
        [("run_id", ASCENDING)],
        name="run_lookup",
        background=True
    )

    # ── fault_events ───────────────────────────────────────────────
    db["fault_events"].create_index(
        [("experiment_id", ASCENDING)],
        name="experiment_lookup",
        background=True
    )
    db["fault_events"].create_index(
        [("fault_type", ASCENDING),
         ("target_service", ASCENDING)],
        name="fault_type_target",
        background=True
    )

    # ── experiment_runs ────────────────────────────────────────────
    db["experiment_runs"].create_index(
        [("experiment_id", ASCENDING),
         ("run_id", ASCENDING)],
        name="exp_run_lookup",
        background=True
    )

    # ── traces ─────────────────────────────────────────────────────
    db["traces"].create_index(
        [("experiment_id", ASCENDING),
         ("start_epoch", ASCENDING)],
        name="exp_time",
        background=True
    )
    db["traces"].create_index(
        [("service", ASCENDING),
         ("start_epoch", ASCENDING)],
        name="service_time",
        background=True
    )

    
    db["analysis_results"].create_index(
        [("experiment_id", ASCENDING)],
        name="experiment_lookup",
        background=True
    )

    print("✅ All collections and indexes initialized successfully.")
    print("Collections created:")
    for name in db.list_collection_names():
        print(f"  - {name}")


if __name__ == "__main__":
    initialize_collections_and_indexes()