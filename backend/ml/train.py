"""
SkyGrid ML — Model Training Pipeline
=======================================
Trains and evaluates mission-cost prediction models.

Models trained:
  1. LinearRegression (simple reference baseline)
  2. GradientBoostingRegressor (candidate ML model)

Both predict two targets jointly using MultiOutputRegressor:
  - completion_time_s: expected mission duration (seconds)
  - energy_consumed_pct: expected battery consumed (% points)

Model selection uses validation-set RMSE, not assumption that complex = better.

Outputs:
  - backend/ml/models/model_<target>_<name>.joblib
  - results/ml_metrics.json
  - results/ml_feature_importance.json (tree model only)

IMPORTANT: These models are trained on simulator-generated data. Predictions
are approximations of the same physics model used by the simulator. Do not
claim real-world accuracy without independent real-world validation.
"""

from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.linear_model import LinearRegression, Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.multioutput import MultiOutputRegressor
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from backend.ml.data_generation import FEATURE_NAMES, LABEL_NAMES
from backend.ml.dataset import prepare_dataset, DATA_DIR

logger = logging.getLogger(__name__)

MODELS_DIR = Path(__file__).parent / "models"
RESULTS_DIR = Path(__file__).resolve().parents[2] / "results"


# ── Metrics ───────────────────────────────────────────────────────────────────

def regression_metrics(y_true: np.ndarray, y_pred: np.ndarray, label: str) -> dict:
    """Compute MAE, RMSE, and R² for one target."""
    mae = mean_absolute_error(y_true, y_pred)
    rmse = np.sqrt(mean_squared_error(y_true, y_pred))
    r2 = r2_score(y_true, y_pred)
    return {
        f"{label}_mae": round(float(mae), 4),
        f"{label}_rmse": round(float(rmse), 4),
        f"{label}_r2": round(float(r2), 4),
    }


# ── Training ──────────────────────────────────────────────────────────────────

def train(data_dir: Path = DATA_DIR, seed: int = 42) -> dict:
    """
    Full training and evaluation pipeline.
    Returns a dict of all metrics (to be saved as ml_metrics.json).
    """
    import joblib

    # ── Load data ──
    train_path = data_dir / "train.csv"
    val_path = data_dir / "val.csv"
    test_path = data_dir / "test.csv"

    if not train_path.exists():
        logger.info("Splits not found; running dataset preparation first.")
        splits = prepare_dataset(data_dir / "raw_episodes.csv", data_dir, seed=seed)
        train_df, val_df, test_df = splits["train"], splits["val"], splits["test"]
    else:
        train_df = pd.read_csv(train_path)
        val_df = pd.read_csv(val_path)
        test_df = pd.read_csv(test_path)

    X_train = train_df[FEATURE_NAMES].values.astype(float)
    y_train = train_df[LABEL_NAMES].values.astype(float)
    X_val = val_df[FEATURE_NAMES].values.astype(float)
    y_val = val_df[LABEL_NAMES].values.astype(float)
    X_test = test_df[FEATURE_NAMES].values.astype(float)
    y_test = test_df[LABEL_NAMES].values.astype(float)

    logger.info(
        "Data loaded: train=%d val=%d test=%d features=%d targets=%d",
        len(X_train), len(X_val), len(X_test), len(FEATURE_NAMES), len(LABEL_NAMES),
    )

    # ── Define model candidates ──
    model_configs = {
        "linear_ridge": Pipeline([
            ("scaler", StandardScaler()),
            ("model", MultiOutputRegressor(Ridge(alpha=1.0, random_state=seed))),
        ]),
        "gradient_boosting": Pipeline([
            ("scaler", StandardScaler()),
            ("model", MultiOutputRegressor(
                GradientBoostingRegressor(
                    n_estimators=200,
                    max_depth=4,
                    learning_rate=0.05,
                    subsample=0.8,
                    random_state=seed,
                )
            )),
        ]),
    }

    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    all_metrics: dict = {
        "dataset_version": "v1",
        "data_source": "synthetic_simulation",
        "feature_names": FEATURE_NAMES,
        "label_names": LABEL_NAMES,
        "n_train": len(X_train),
        "n_val": len(X_val),
        "n_test": len(X_test),
        "models": {},
        "selected_model": None,
        "note": (
            "Models trained on simulator-generated data. "
            "Predictions approximate the same physics model used by the simulator. "
            "Real-world accuracy is unvalidated."
        ),
    }

    best_model_name: str | None = None
    best_val_rmse: float = float("inf")
    best_pipeline = None

    for name, pipeline in model_configs.items():
        logger.info("Training model: %s", name)
        t0 = time.time()
        pipeline.fit(X_train, y_train)
        train_s = time.time() - t0

        # Validation metrics
        y_val_pred = pipeline.predict(X_val)
        val_metrics: dict = {}
        for i, label in enumerate(LABEL_NAMES):
            val_metrics.update(regression_metrics(y_val[:, i], y_val_pred[:, i], f"val_{label}"))

        # Hold-out test metrics
        y_test_pred = pipeline.predict(X_test)
        test_metrics: dict = {}
        for i, label in enumerate(LABEL_NAMES):
            test_metrics.update(regression_metrics(y_test[:, i], y_test_pred[:, i], f"test_{label}"))

        # Training set metrics (for overfitting check)
        y_train_pred = pipeline.predict(X_train)
        train_metrics: dict = {}
        for i, label in enumerate(LABEL_NAMES):
            train_metrics.update(regression_metrics(y_train[:, i], y_train_pred[:, i], f"train_{label}"))

        model_result = {
            "train_time_s": round(train_s, 3),
            **train_metrics,
            **val_metrics,
            **test_metrics,
        }
        all_metrics["models"][name] = model_result

        # Select best by validation RMSE (average across targets)
        val_rmse_avg = np.mean([
            val_metrics.get(f"val_{label}_rmse", float("inf"))
            for label in LABEL_NAMES
        ])
        logger.info(
            "  %s | val_rmse_avg=%.4f | train_time=%.2fs", name, val_rmse_avg, train_s
        )

        if val_rmse_avg < best_val_rmse:
            best_val_rmse = val_rmse_avg
            best_model_name = name
            best_pipeline = pipeline

    all_metrics["selected_model"] = best_model_name
    all_metrics["selected_model_val_rmse_avg"] = round(best_val_rmse, 4)

    # ── Save best model ──
    if best_pipeline is not None:
        model_path = MODELS_DIR / "best_model.joblib"
        joblib.dump(best_pipeline, model_path)
        logger.info("Saved best model (%s) to %s", best_model_name, model_path)
        all_metrics["model_path"] = str(model_path)

        # Save feature importance if available (gradient boosting)
        try:
            inner_models = best_pipeline.named_steps["model"].estimators_
            importance_data = {}
            for label, est in zip(LABEL_NAMES, inner_models):
                if hasattr(est, "feature_importances_"):
                    importance_data[label] = dict(
                        zip(FEATURE_NAMES, est.feature_importances_.tolist())
                    )
            if importance_data:
                imp_path = RESULTS_DIR / "ml_feature_importance.json"
                with open(imp_path, "w") as f:
                    json.dump(importance_data, f, indent=2)
                logger.info("Feature importances saved to %s", imp_path)
        except (AttributeError, IndexError):
            pass  # Linear models don't have feature_importances_

    # ── Save all metrics ──
    metrics_path = RESULTS_DIR / "ml_metrics.json"
    with open(metrics_path, "w") as f:
        json.dump(all_metrics, f, indent=2)
    logger.info("ML metrics saved to %s", metrics_path)

    return all_metrics


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    import argparse

    parser = argparse.ArgumentParser(description="Train SkyGrid ML models")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--data-dir", type=str, default=str(DATA_DIR))
    args = parser.parse_args()

    metrics = train(data_dir=Path(args.data_dir), seed=args.seed)
    print(f"\n[train] Selected model: {metrics['selected_model']}")
    print(f"[train] Validation RMSE (avg): {metrics.get('selected_model_val_rmse_avg')}")
    for label in LABEL_NAMES:
        m = metrics["models"].get(metrics["selected_model"], {})
        print(
            f"  {label}: MAE={m.get(f'test_{label}_mae')} "
            f"RMSE={m.get(f'test_{label}_rmse')} "
            f"R²={m.get(f'test_{label}_r2')}"
        )
