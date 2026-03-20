"""
Week 9 — OpenStack Dataset Validation
Compares our platform results against DSSELab OpenStack fault injection dataset.
"""
import csv
import json
import time
from pymongo import MongoClient

DATASET_FILES = {
    "nova":    "validation/nova.tsv",
    "cinder":  "validation/cinder.tsv",
    "neutron": "validation/neutron.tsv"
}

# Map OpenStack fault types to our fault categories
FAULT_TYPE_MAP = {
    "OPENSTACK_MISSING_FUNCTION_CALL": "crash",
    "OPENSTACK_WRONG_RETURN_VALUE":    "network",
    "OPENSTACK_WRONG_VARIABLE_VALUE":  "memory",
    "OPENSTACK_MISSING_VARIABLE_ASSIGNMENT": "cpu"
}

def load_openstack_dataset() -> dict:
    """Load and parse all three OpenStack TSV files"""
    all_tests = {}

    for component, filepath in DATASET_FILES.items():
        tests = []
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f, delimiter="\t")
                for row in reader:
                    tests.append(row)
            all_tests[component] = tests
            print(f"[VALIDATION] Loaded {len(tests)} tests "
                  f"from {component}")
        except FileNotFoundError:
            print(f"[VALIDATION] File not found: {filepath}")
            all_tests[component] = []

    return all_tests


def analyze_openstack_dataset(dataset: dict) -> dict:
    """
    Extract failure statistics from OpenStack dataset.
    Computes failure rates per fault type per component.
    """
    stats = {}

    for component, tests in dataset.items():
        if not tests:
            continue

        total = len(tests)
        failures_r1 = sum(
            1 for t in tests
            if t.get("ASSERTION_R1", "").startswith("FAILURE")
        )
        failures_r2 = sum(
            1 for t in tests
            if t.get("ASSERTION_R2", "").startswith("FAILURE")
        )

        # Fault type breakdown
        fault_type_counts = {}
        fault_type_failures = {}

        for test in tests:
            raw_type = test.get("FAULT_TYPE", "")
            # Extract base fault type (before the dash)
            base_type = raw_type.split("-")[0] if "-" in raw_type else raw_type
            mapped = FAULT_TYPE_MAP.get(base_type, "unknown")

            fault_type_counts[mapped] = fault_type_counts.get(mapped, 0) + 1
            if test.get("ASSERTION_R1", "").startswith("FAILURE"):
                fault_type_failures[mapped] = \
                    fault_type_failures.get(mapped, 0) + 1

        # Compute failure rates per fault type
        failure_rates = {}
        for ft, count in fault_type_counts.items():
            failures = fault_type_failures.get(ft, 0)
            failure_rates[ft] = round(failures / count * 100, 1)

        stats[component] = {
            "total_tests": total,
            "failure_count_r1": failures_r1,
            "failure_rate_r1_pct": round(failures_r1 / total * 100, 1),
            "failure_count_r2": failures_r2,
            "failure_rate_r2_pct": round(failures_r2 / total * 100, 1),
            "fault_type_counts": fault_type_counts,
            "fault_type_failure_rates": failure_rates
        }

        print(f"\n[VALIDATION] {component.upper()}:")
        print(f"  Total tests:    {total}")
        print(f"  Failure rate R1: {stats[component]['failure_rate_r1_pct']}%")
        print(f"  Fault types:    {fault_type_counts}")

    return stats


def load_our_results() -> dict:
    """Load our platform results from MongoDB"""
    db = MongoClient("mongodb://localhost:27017/")["platform_db"]

    # Get all resilience scores
    scores = list(db["analysis_results"].find(
        {"analysis_type": "resilience_score"},
        {"_id": 0}
    ))

    # Get all degradation results
    degradations = list(db["analysis_results"].find(
        {"analysis_type": "degradation"},
        {"_id": 0}
    ))

    # Get all fault events
    faults = list(db["fault_events"].find({}, {"_id": 0}))

    # Compute our failure rates per fault type
    fault_type_results = {}
    for fault in faults:
        ft = fault.get("fault_type", "unknown")
        if ft not in fault_type_results:
            fault_type_results[ft] = {
                "total": 0,
                "scores": [],
                "latency_increases": []
            }
        fault_type_results[ft]["total"] += 1

    # Add scores
    for score in scores:
        run_id = score.get("run_id")
        fault = next(
            (f for f in faults if f.get("run_id") == run_id), None
        )
        if fault:
            ft = fault.get("fault_type", "unknown")
            if ft in fault_type_results:
                fault_type_results[ft]["scores"].append(
                    score.get("final_resilience_score", 1.0)
                )

    # Add latency increases
    for deg in degradations:
        run_id = deg.get("run_id")
        fault = next(
            (f for f in faults if f.get("run_id") == run_id), None
        )
        if fault:
            ft = fault.get("fault_type", "unknown")
            if ft in fault_type_results:
                for service in ["service_a", "service_b", "service_c"]:
                    lat = deg.get("latency_degradation", {}).get(
                        service, {}
                    ).get("latency_increase_pct")
                    if lat is not None:
                        fault_type_results[ft]["latency_increases"].append(lat)

    # Compute averages
    our_stats = {}
    for ft, data in fault_type_results.items():
        scores_list = data["scores"]
        lat_list    = data["latency_increases"]
        our_stats[ft] = {
            "total_experiments": data["total"],
            "avg_resilience_score": round(
                sum(scores_list) / len(scores_list), 3
            ) if scores_list else None,
            "avg_latency_increase_pct": round(
                sum(lat_list) / len(lat_list), 1
            ) if lat_list else None,
            "failure_rate_pct": round(
                (1 - sum(scores_list) / len(scores_list)) * 100, 1
            ) if scores_list else None
        }

    print(f"\n[VALIDATION] Our platform results:")
    for ft, data in our_stats.items():
        print(f"  {ft}: score={data['avg_resilience_score']}, "
              f"failure_rate={data['failure_rate_pct']}%")

    return our_stats


def compare_results(
    openstack_stats: dict, our_stats: dict
) -> dict:
    """
    Compare OpenStack dataset results with our platform results.
    Produces comparison table for research paper.
    """
    print(f"\n{'='*60}")
    print("VALIDATION COMPARISON RESULTS")
    print(f"{'='*60}")

    comparison = {}

    # Map OpenStack components to fault types
    os_fault_rates = {}
    for component, stats in openstack_stats.items():
        for ft, rate in stats.get(
            "fault_type_failure_rates", {}
        ).items():
            if ft not in os_fault_rates:
                os_fault_rates[ft] = []
            os_fault_rates[ft].append(rate)

    # Average across components
    os_avg_rates = {
        ft: round(sum(rates) / len(rates), 1)
        for ft, rates in os_fault_rates.items()
    }

    print(f"\n{'Fault Type':<12} {'OpenStack':<20} {'Our Platform':<20} {'Delta'}")
    print("-" * 65)

    for ft in set(list(os_avg_rates.keys()) + list(our_stats.keys())):
        os_rate  = os_avg_rates.get(ft)
        our_rate = our_stats.get(ft, {}).get("failure_rate_pct")

        if os_rate is not None and our_rate is not None:
            delta = round(abs(os_rate - our_rate), 1)
            similar = "✅ Similar" if delta < 20 else "⚠ Different"
        else:
            delta   = None
            similar = "N/A"

        comparison[ft] = {
            "openstack_failure_rate_pct": os_rate,
            "our_failure_rate_pct":       our_rate,
            "delta_pct":                  delta,
            "validation_result":          similar
        }

        print(f"{ft:<12} "
              f"{str(os_rate)+'%' if os_rate else 'N/A':<20} "
              f"{str(our_rate)+'%' if our_rate else 'N/A':<20} "
              f"{str(delta)+'%' if delta else 'N/A'} {similar}")

    return comparison


def save_validation_results(
    openstack_stats: dict,
    our_stats: dict,
    comparison: dict
):
    """Save validation results to MongoDB"""
    db = MongoClient("mongodb://localhost:27017/")["platform_db"]
    doc = {
        "analysis_type": "openstack_validation",
        "computed_at": time.time(),
        "openstack_dataset_stats": openstack_stats,
        "our_platform_stats": our_stats,
        "comparison": comparison,
        "dataset_source": "DSSELab Fault-Injection-Dataset",
        "dataset_url": "https://github.com/dessertlab/Fault-Injection-Dataset"
    }
    db["analysis_results"].insert_one(doc)

    # Also save to JSON for dashboard
    with open("validation/comparison_results.json", "w") as f:
        json.dump(doc, f, indent=2, default=str)

    print(f"\n[VALIDATION] Results saved to MongoDB and "
          f"validation/comparison_results.json ✅")
    return doc


if __name__ == "__main__":
    print("="*60)
    print("WEEK 9 — OPENSTACK DATASET VALIDATION")
    print("="*60)

    # Load datasets
    dataset     = load_openstack_dataset()
    os_stats    = analyze_openstack_dataset(dataset)
    our_stats   = load_our_results()
    comparison  = compare_results(os_stats, our_stats)
    save_validation_results(os_stats, our_stats, comparison)

    print(f"\n{'='*60}")
    print("VALIDATION COMPLETE")
    print("="*60)