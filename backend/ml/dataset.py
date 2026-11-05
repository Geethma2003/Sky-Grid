"""
SkyGrid ML — Dataset Preparation
==================================
Loads raw episodes, validates them, splits into train/val/test sets,
and saves processed splits.

Validation checks:
  - Required columns present
  - No null/NaN values
  - No duplicate episode IDs
  - Label range sanity (completion_time > 0, energy 0-100)
  - Feature range sanity

Split strategy:
  - Chronological by episode seed to prevent leakage
  - 70% train / 15% val / 15% test
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split

from backend.ml.data_generation import FEATURE_NAMES, LABEL_NAMES

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent / "data"
RAW_FILE = DATA_DIR / "raw_episodes.csv"


# ── Validation ────────────────────────────────────────────────────────────────

def validate_dataset(df: pd.DataFrame) -> tuple[bool, list[str]]:
    """
    Validate the raw dataset. Returns (passed, list_of_issues).
    All issues are reported even if some pass.
    """
    issues: list[str] = []

    # Required columns
    required = set(FEATURE_NAMES + LABEL_NAMES + ["episode_id", "seed"])
    missing = required - set(df.columns)
    if missing:
        issues.append(f"Missing columns: {sorted(missing)}")

    # Null values
    null_counts = df[FEATURE_NAMES + LABEL_NAMES].isnull().sum()
    for col, count in null_counts.items():
        if count > 0:
            issues.append(f"Column '{col}' has {count} null values")

    # Duplicate episode IDs
    if "episode_id" in df.columns:
        dupes = df["episode_id"].duplicated().sum()
        if dupes > 0:
            issues.append(f"{dupes} duplicate episode_id values found")

    # Label sanity
    if "completion_time_s" in df.columns:
        neg = (df["completion_time_s"] <= 0).sum()
        if neg > 0:
            issues.append(f"{neg} episodes with completion_time_s <= 0")

    if "energy_consumed_pct" in df.columns:
        oob = ((df["energy_consumed_pct"] < 0) | (df["energy_consumed_pct"] > 100)).sum()
        if oob > 0:
            issues.append(f"{oob} episodes with energy_consumed_pct outside [0, 100]")

    # Feature sanity
    for col in ["battery_start_pct", "battery_soh_pct"]:
        if col in df.columns:
            oob = ((df[col] < 0) | (df[col] > 100)).sum()
            if oob > 0:
                issues.append(f"{oob} rows with {col} outside [0, 100]")

    if "route_dist_km" in df.columns:
        neg = (df["route_dist_km"] < 0).sum()
        if neg > 0:
            issues.append(f"{neg} rows with route_dist_km < 0")

    return len(issues) == 0, issues


# ── Preparation ───────────────────────────────────────────────────────────────

def prepare_dataset(
    raw_path: Path = RAW_FILE,
    output_dir: Path = DATA_DIR,
    val_frac: float = 0.15,
    test_frac: float = 0.15,
    seed: int = 42,
) -> dict[str, pd.DataFrame]:
    """
    Load, validate, and split the dataset.

    Split strategy: sort by episode seed (proxy for generation order) to
    avoid leakage between related scenarios, then split temporally.
    """
    if not raw_path.exists():
        raise FileNotFoundError(
            f"Raw data not found at {raw_path}. "
            "Run `python -m backend.ml.data_generation` first."
        )

    df = pd.read_csv(raw_path)
    logger.info("Loaded %d rows from %s", len(df), raw_path)

    # Cast feature/label columns to float
    for col in FEATURE_NAMES + LABEL_NAMES:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    passed, issues = validate_dataset(df)
    if issues:
        for issue in issues:
            logger.warning("Dataset issue: %s", issue)
    if not passed:
        raise ValueError(f"Dataset validation failed with {len(issues)} issues. See logs.")

    # Sort by seed for temporal split
    if "seed" in df.columns:
        df = df.sort_values("seed").reset_index(drop=True)

    # Split: first 70% train, next 15% val, last 15% test
    n = len(df)
    n_test = max(1, int(n * test_frac))
    n_val = max(1, int(n * val_frac))
    n_train = n - n_val - n_test

    train_df = df.iloc[:n_train].copy()
    val_df = df.iloc[n_train:n_train + n_val].copy()
    test_df = df.iloc[n_train + n_val:].copy()

    logger.info(
        "Split: train=%d val=%d test=%d (total=%d)",
        len(train_df), len(val_df), len(test_df), n
    )

    # Save splits
    output_dir.mkdir(parents=True, exist_ok=True)
    train_df.to_csv(output_dir / "train.csv", index=False)
    val_df.to_csv(output_dir / "val.csv", index=False)
    test_df.to_csv(output_dir / "test.csv", index=False)

    # Save metadata
    meta = {
        "dataset_version": "v1",
        "raw_file": str(raw_path),
        "n_total": n,
        "n_train": len(train_df),
        "n_val": len(val_df),
        "n_test": len(test_df),
        "feature_names": FEATURE_NAMES,
        "label_names": LABEL_NAMES,
        "split_strategy": "temporal_by_seed",
        "val_frac": val_frac,
        "test_frac": test_frac,
        "seed": seed,
        "data_source": "synthetic_simulation",
        "note": (
            "All data generated from SkyGrid simulation physics model. "
            "Not validated against physical drone hardware. "
            "ML predictions are valid only within simulator assumptions."
        ),
    }
    with open(output_dir / "dataset_meta.json", "w") as f:
        json.dump(meta, f, indent=2)

    logger.info("Saved train/val/test splits and metadata to %s", output_dir)

    return {"train": train_df, "val": val_df, "test": test_df}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    splits = prepare_dataset()
    print(f"[dataset] Train: {len(splits['train'])} | Val: {len(splits['val'])} | Test: {len(splits['test'])}")
