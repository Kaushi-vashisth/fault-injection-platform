import time
import json
import numpy as np
from pymongo import MongoClient
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
from sklearn.tree import DecisionTreeClassifier
from sklearn.model_selection import cross_val_score, LeaveOneOut
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import (
    classification_report, confusion_matrix, accuracy_score
)
import pickle
import os

from analytics.ml.feature_extraction import (
    extract_all_features, features_to_matrix,
    FAULT_LABEL_MAP, LABEL_NAME_MAP
)

MODEL_PATH = "analytics/ml/trained_model.pkl"
SCALER_PATH = "analytics/ml/trained_scaler.pkl"


class FaultClassifier:

    def __init__(self):
        self.model   = None
        self.scaler  = StandardScaler()
        self.feature_names = None
        self.db = MongoClient("mongodb://localhost:27017/")["platform_db"]

    def train(self, feature_rows: list) -> dict:
        """
        Train fault classifier on extracted features.
        Uses RandomForest as primary model.
        """
        print(f"\n[ML] Training on {len(feature_rows)} samples")

        X, y, feature_names = features_to_matrix(feature_rows)

        if X is None or len(X) == 0:
            print("[ML] No training data available")
            return {}

        self.feature_names = feature_names

        # Scale features
        X_scaled = self.scaler.fit_transform(X)

        # Choose model based on dataset size
        if len(X) < 10:
            print("[ML] Small dataset — using Decision Tree")
            self.model = DecisionTreeClassifier(
                max_depth=3,
                random_state=42
            )
        else:
            print("[ML] Using Random Forest")
            self.model = RandomForestClassifier(
                n_estimators=100,
                max_depth=5,
                random_state=42,
                class_weight="balanced"
            )

        self.model.fit(X_scaled, y)

        # Evaluate
        results = self._evaluate(X_scaled, y)
        results["feature_count"]  = len(feature_names)
        results["training_samples"] = len(X)

        # Save model
        self._save_model()

        # Save results to MongoDB
        self._save_training_results(results, feature_rows)

        print(f"[ML] Training complete — accuracy: {results.get('accuracy')}")
        return results

    def predict(self, run_id: str) -> dict:
        """Predict fault type for a single run"""
        if not self.model:
            self._load_model()

        from analytics.ml.feature_extraction import extract_features_for_run
        row = extract_features_for_run(run_id)

        if not row:
            return {"error": "No features found for run"}

        feature_names = sorted(row["features"].keys())
        x = np.array([[row["features"].get(f, 0) or 0
                       for f in feature_names]])
        x_scaled = self.scaler.transform(x)

        pred_label    = int(self.model.predict(x_scaled)[0])
        pred_proba    = self.model.predict_proba(x_scaled)[0]
        true_label    = row["label"]

        result = {
            "run_id": run_id,
            "predicted_fault": LABEL_NAME_MAP.get(pred_label, "unknown"),
            "true_fault":      LABEL_NAME_MAP.get(true_label, "unknown"),
            "correct":         pred_label == true_label,
            "confidence":      round(float(max(pred_proba)), 3),
            "probabilities": {
                LABEL_NAME_MAP[i]: round(float(p), 3)
                for i, p in enumerate(pred_proba)
                if i in LABEL_NAME_MAP
            }
        }

        print(f"[ML] Prediction: {result['predicted_fault']} "
              f"(confidence: {result['confidence']}) "
              f"— correct: {result['correct']}")
        return result

    def _evaluate(self, X_scaled: np.ndarray, y: np.ndarray) -> dict:
        """Evaluate model with cross-validation"""
        n_samples = len(X_scaled)

        if n_samples < 4:
            # Too few samples for CV — use train accuracy
            y_pred   = self.model.predict(X_scaled)
            accuracy = round(accuracy_score(y, y_pred), 3)
            print(f"[ML] Train accuracy (small dataset): {accuracy}")
            return {
                "accuracy": accuracy,
                "cv_method": "train_accuracy",
                "cv_scores": [accuracy]
            }
        elif n_samples < 10:
            # Leave-one-out cross validation
            loo    = LeaveOneOut()
            scores = cross_val_score(
                self.model, X_scaled, y, cv=loo, scoring="accuracy"
            )
            print(f"[ML] LOO-CV scores: {scores}")
        else:
            # 5-fold cross validation
            scores = cross_val_score(
                self.model, X_scaled, y, cv=5, scoring="accuracy"
            )
            print(f"[ML] 5-Fold CV scores: {scores}")

        y_pred = self.model.predict(X_scaled)

        return {
            "accuracy":    round(float(np.mean(scores)), 3),
            "cv_std":      round(float(np.std(scores)), 3),
            "cv_scores":   [round(float(s), 3) for s in scores],
            "cv_method":   "leave_one_out" if n_samples < 10 else "5_fold",
            "train_accuracy": round(float(accuracy_score(y, y_pred)), 3),
            "confusion_matrix": confusion_matrix(y, y_pred).tolist(),
            "classification_report": classification_report(
                y, y_pred,
                target_names=[LABEL_NAME_MAP.get(i, str(i))
                               for i in sorted(set(y))],
                output_dict=True
            )
        }

    def get_feature_importance(self) -> list:
        """Return top features by importance"""
        if not self.model or not self.feature_names:
            return []

        if not hasattr(self.model, "feature_importances_"):
            return []

        importances = self.model.feature_importances_
        ranked = sorted(
            zip(self.feature_names, importances),
            key=lambda x: x[1],
            reverse=True
        )

        print("\n[ML] Top 10 features:")
        for name, imp in ranked[:10]:
            print(f"  {name}: {round(imp, 4)}")

        return [{"feature": n, "importance": round(float(i), 4)}
                for n, i in ranked]

    def _save_model(self):
        os.makedirs("analytics/ml", exist_ok=True)
        with open(MODEL_PATH, "wb") as f:
            pickle.dump(self.model, f)
        with open(SCALER_PATH, "wb") as f:
            pickle.dump(self.scaler, f)
        print(f"[ML] Model saved to {MODEL_PATH}")

    def _load_model(self):
        if os.path.exists(MODEL_PATH):
            with open(MODEL_PATH, "rb") as f:
                self.model = pickle.load(f)
            with open(SCALER_PATH, "rb") as f:
                self.scaler = pickle.load(f)
            print("[ML] Model loaded from disk")

    def _save_training_results(self, results: dict, feature_rows: list):
        doc = {
            "analysis_type": "ml_training",
            "trained_at": time.time(),
            "model_type": type(self.model).__name__,
            "results": results,
            "label_distribution": {
                LABEL_NAME_MAP.get(int(k), str(k)): int(v)
                for k, v in zip(
                    *np.unique(
                        [r["label"] for r in feature_rows],
                        return_counts=True
                    )
                )
            }
        }
        self.db["analysis_results"].insert_one(doc)
        print("[ML] Training results saved to MongoDB ✅")


if __name__ == "__main__":
    clf = FaultClassifier()

    # Extract features from all runs
    feature_rows = extract_all_features()

    if len(feature_rows) == 0:
        print("No data found. Run experiments first.")
    else:
        # Train
        results = clf.train(feature_rows)
        print(f"\nAccuracy:  {results.get('accuracy')}")
        print(f"CV Method: {results.get('cv_method')}")

        # Feature importance
        clf.get_feature_importance()

        # Predict all runs
        print("\n[ML] Predictions on all runs:")
        for row in feature_rows:
            clf.predict(row["run_id"])