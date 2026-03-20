import time
from pymongo import MongoClient

# ─── Weight Configuration ─────────────────────────────────────────
# These weights sum to 1.0
# Justify in paper: MTTR weighted highest as recovery speed
# is the most operationally critical metric
WEIGHTS = {
    "mttr":              0.35,
    "latency_increase":  0.25,
    "throughput_drop":   0.25,
    "error_rate_delta":  0.15
}

# ─── Normalization Bounds ─────────────────────────────────────────
# Maximum expected values — used to normalize metrics to [0,1]
# Adjust based on your experimental observations
BOUNDS = {
    "mttr_max_sec":          300.0,   # 5 minutes max recovery
    "latency_increase_max":  500.0,   # 500% max latency increase
    "throughput_drop_max":   100.0,   # 100% max throughput drop
    "error_rate_max":        100.0    # 100% max error rate
}


class ResilienceScorer:

    def __init__(self, mongo_uri: str = "mongodb://localhost:27017/"):
        self.db = MongoClient(mongo_uri)["platform_db"]

    def compute_score(self, run_id: str) -> dict:
        """
        Compute composite resilience score for a completed experiment run.

        R_component(s) = Σ wᵢ · normalize(mᵢ(s))
        R_system = mean of all component scores

        Score range: 0.0 (completely non-resilient) to 1.0 (fully resilient)
        """
        print(f"\n[SCORER] Computing resilience score for run: {run_id}")

        # Load analysis results from MongoDB
        mttr_doc = self.db["analysis_results"].find_one({
            "run_id": run_id,
            "analysis_type": "mttr"
        })
        degradation_doc = self.db["analysis_results"].find_one({
            "run_id": run_id,
            "analysis_type": "degradation"
        })
        propagation_doc = self.db["analysis_results"].find_one({
            "run_id": run_id,
            "analysis_type": "propagation"
        })

        if not any([mttr_doc, degradation_doc]):
            print("[SCORER] No analysis results found — run Spark jobs first")
            return {}

        experiment_id = (mttr_doc or degradation_doc).get("experiment_id")
        component_scores = {}

        for service in ["service_a", "service_b", "service_c"]:
            score = self._compute_component_score(
                service, mttr_doc, degradation_doc, propagation_doc
            )
            component_scores[service] = score
            print(f"[SCORER] {service}: {round(score, 3)}")

        # System-level score — weighted by service position
        # Service B is most critical (fault origin in most experiments)
        service_weights = {
            "service_a": 0.3,
            "service_b": 0.5,
            "service_c": 0.2
        }
        system_score = round(
            sum(
                component_scores[s] * service_weights[s]
                for s in component_scores
            ), 3
        )
        print(f"[SCORER] System score: {system_score}")

        # Blast radius penalty
        blast_penalty = 0.0
        if propagation_doc:
            blast = propagation_doc.get("blast_radius", {})
            blast_pct = blast.get("blast_radius_pct", 0)
            blast_penalty = round(blast_pct / 100 * 0.1, 3)

        final_score = round(
            max(0.0, min(1.0, system_score - blast_penalty)), 3
        )
        print(f"[SCORER] Final score (with blast penalty): {final_score}")

        result = {
            "experiment_id": experiment_id,
            "run_id": run_id,
            "analysis_type": "resilience_score",
            "computed_at": time.time(),
            "component_scores": component_scores,
            "system_score": system_score,
            "blast_radius_penalty": blast_penalty,
            "final_resilience_score": final_score,
            "weights_used": WEIGHTS,
            "score_interpretation": self._interpret_score(final_score)
        }

        # Save to MongoDB
        self.db["analysis_results"].insert_one(result)
        print(f"[SCORER] Score saved to MongoDB ✅")
        return result

    def _compute_component_score(
        self,
        service: str,
        mttr_doc: dict,
        degradation_doc: dict,
        propagation_doc: dict
    ) -> float:
        """
        Compute resilience score for a single service.
        Each metric normalized to [0,1] then weighted.
        """
        scores = []

        # ── MTTR score ────────────────────────────────────────────
        if mttr_doc:
            mttr_val = mttr_doc.get(
                "mttr_per_service", {}
            ).get(service)
            mttr_score = self._normalize_inverse(
                mttr_val, BOUNDS["mttr_max_sec"]
            )
            scores.append(("mttr", mttr_score, WEIGHTS["mttr"]))

        # ── Latency increase score ────────────────────────────────
        if degradation_doc:
            lat = degradation_doc.get(
                "latency_degradation", {}
            ).get(service, {})
            lat_val = lat.get("latency_increase_pct")
            lat_score = self._normalize_inverse(
                lat_val, BOUNDS["latency_increase_max"]
            )
            scores.append((
                "latency_increase", lat_score,
                WEIGHTS["latency_increase"]
            ))

        # ── Throughput drop score ─────────────────────────────────
        if degradation_doc:
            tput = degradation_doc.get(
                "throughput_drop", {}
            ).get(service, {})
            tput_val = tput.get("throughput_drop_pct")
            tput_score = self._normalize_inverse(
                tput_val, BOUNDS["throughput_drop_max"]
            )
            scores.append((
                "throughput_drop", tput_score,
                WEIGHTS["throughput_drop"]
            ))

        # ── Error rate score ──────────────────────────────────────
        if degradation_doc:
            err = degradation_doc.get(
                "error_rate_delta", {}
            ).get(service, {})
            err_val = err.get("error_rate_delta")
            err_score = self._normalize_inverse(
                err_val, BOUNDS["error_rate_max"]
            )
            scores.append((
                "error_rate_delta", err_score,
                WEIGHTS["error_rate_delta"]
            ))

        if not scores:
            return 1.0  # No data = assume resilient

        # Weighted sum
        total_weight = sum(w for _, _, w in scores)
        weighted_sum = sum(s * w for _, s, w in scores)

        if total_weight == 0:
            return 1.0

        return round(weighted_sum / total_weight, 3)

    def _normalize_inverse(
        self, value, max_value: float
    ) -> float:
        """
        Normalize a metric to [0,1] where:
        0 = worst (max degradation)
        1 = best (no degradation)

        normalize(x) = 1 - clamp(x / max_value, 0, 1)
        """
        if value is None:
            return 1.0  # No data = no degradation detected
        if max_value == 0:
            return 1.0
        clamped = max(0.0, min(float(value), max_value))
        return round(1.0 - (clamped / max_value), 3)

    def _interpret_score(self, score: float) -> str:
        """Human readable score interpretation"""
        if score >= 0.85:
            return "Highly Resilient"
        elif score >= 0.70:
            return "Resilient"
        elif score >= 0.50:
            return "Moderately Resilient"
        elif score >= 0.30:
            return "Low Resilience"
        else:
            return "Critical — Very Low Resilience"

    def get_all_scores(self) -> list:
        """Retrieve all computed resilience scores"""
        return list(
            self.db["analysis_results"]
            .find(
                {"analysis_type": "resilience_score"},
                {"_id": 0}
            )
            .sort("computed_at", -1)
        )

    def compare_experiments(self, experiment_ids: list) -> dict:
        """
        Compare resilience scores across multiple experiments.
        Useful for paper results table.
        """
        comparison = {}
        for exp_id in experiment_ids:
            scores = list(
                self.db["analysis_results"].find(
                    {
                        "experiment_id": exp_id,
                        "analysis_type": "resilience_score"
                    },
                    {"_id": 0}
                )
            )
            if scores:
                # Average across runs
                avg_score = round(
                    sum(s["final_resilience_score"]
                        for s in scores) / len(scores), 3
                )
                comparison[exp_id] = {
                    "avg_resilience_score": avg_score,
                    "run_count": len(scores),
                    "interpretation": self._interpret_score(avg_score)
                }
        return comparison


if __name__ == "__main__":
    from pymongo import MongoClient

    scorer = ResilienceScorer()
    db = MongoClient("mongodb://localhost:27017/")["platform_db"]

    # Score the most recent run
    latest = db["experiment_runs"].find_one(
        sort=[("created_at", -1)]
    )

    if latest:
        run_id = latest["run_id"]
        result = scorer.compute_score(run_id)
        print(f"\n{'='*50}")
        print(f"RESILIENCE SCORE: "
              f"{result.get('final_resilience_score')}")
        print(f"INTERPRETATION:   "
              f"{result.get('score_interpretation')}")
        print(f"{'='*50}")
    else:
        print("No experiment runs found.")
