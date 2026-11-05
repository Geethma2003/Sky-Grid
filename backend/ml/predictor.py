"""
SkyGrid ML — Predictor
========================
Wraps the trained model for use in the dispatch decision pipeline.

The predictor:
  1. Loads the best model from disk (if available).
  2. Accepts a candidate assignment (drone + order features).
  3. Returns predicted completion_time_s and energy_consumed_pct.
  4. Falls back safely to deterministic estimates if the model is
     unavailable, invalid, or produces implausible outputs.

Safety contract:
  - The predictor NEVER authorises an unsafe assignment.
  - All hard safety checks (battery reserve, payload capacity, SoH threshold)
    are enforced by the dispatcher, not overridden by the model.
  - If the model fails or is absent, the deterministic fallback is used.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

MODELS_DIR = Path(__file__).parent / "models"
MODEL_FILE = MODELS_DIR / "best_model.joblib"

# Fallback physics constants (match simulation_engine.py)
_BASE_WH_KM = 2.8
_SWAP_TIME_S = 90.0
_PAD_WAIT_PER_BUSY_PAD_S = 30.0


@dataclass
class PredictionResult:
    """Outcome of a cost prediction for one candidate assignment."""
    completion_time_s: float
    energy_consumed_pct: float
    used_model: bool              # True = ML model used; False = deterministic fallback
    model_name: str               # Model identifier or "deterministic_fallback"
    feasible: bool                # False if predicted energy > available battery - reserve


class MissionCostPredictor:
    """
    Predicts mission duration and energy consumption for a candidate
    drone assignment.

    Usage:
        predictor = MissionCostPredictor()
        result = predictor.predict(
            route_dist_km=4.5,
            battery_start_pct=85.0,
            battery_soh_pct=94.0,
            payload_kg=2.1,
            drone_speed_kmh=65.0,
            wind_speed_kmh=12.0,
            weather_severity=1.0,
            num_active_drones=2,
            pad_queue_estimate=1,
            priority_ordinal=0,
            motor_hours=342.0,
            alt_segment_ratio=0.7,
        )
    """

    BATTERY_RESERVE_PCT = 20.0   # hard safety reserve; ML cannot override this
    MAX_PLAUSIBLE_TIME_S = 7200.0  # 2 hours — implausible predictions capped
    MAX_PLAUSIBLE_ENERGY_PCT = 100.0

    def __init__(self, model_path: Path = MODEL_FILE):
        self._pipeline = None
        self._model_name = "deterministic_fallback"
        self._load_model(model_path)

    def _load_model(self, path: Path) -> None:
        try:
            import joblib
            if not path.exists():
                logger.warning(
                    "MissionCostPredictor: model file not found at %s. "
                    "Using deterministic fallback.",
                    path,
                )
                return
            self._pipeline = joblib.load(path)
            self._model_name = path.stem
            logger.info("MissionCostPredictor: loaded model from %s", path)
        except Exception as exc:
            logger.error(
                "MissionCostPredictor: failed to load model (%s). "
                "Using deterministic fallback.",
                exc,
            )
            self._pipeline = None

    @property
    def model_available(self) -> bool:
        return self._pipeline is not None

    def predict(
        self,
        route_dist_km: float,
        battery_start_pct: float,
        battery_soh_pct: float,
        payload_kg: float,
        drone_speed_kmh: float,
        wind_speed_kmh: float,
        weather_severity: float,
        num_active_drones: int,
        pad_queue_estimate: int,
        priority_ordinal: int,
        motor_hours: float,
        alt_segment_ratio: float,
    ) -> PredictionResult:
        """
        Predict completion time (s) and energy consumed (%).
        Always checks feasibility against battery reserve.
        """
        # Prepare feature vector (must match FEATURE_NAMES order in data_generation.py)
        X = np.array([[
            route_dist_km,
            battery_start_pct,
            battery_soh_pct,
            payload_kg,
            drone_speed_kmh,
            wind_speed_kmh,
            weather_severity,
            num_active_drones,
            pad_queue_estimate,
            priority_ordinal,
            motor_hours,
            alt_segment_ratio,
        ]], dtype=float)

        used_model = False

        if self._pipeline is not None:
            try:
                pred = self._pipeline.predict(X)[0]
                completion_time_s = float(pred[0])
                energy_consumed_pct = float(pred[1])

                # Sanity-check predictions — fall back if implausible
                if (
                    completion_time_s <= 0
                    or completion_time_s > self.MAX_PLAUSIBLE_TIME_S
                    or energy_consumed_pct < 0
                    or energy_consumed_pct > self.MAX_PLAUSIBLE_ENERGY_PCT
                ):
                    logger.warning(
                        "MissionCostPredictor: implausible prediction "
                        "(time=%.1f, energy=%.1f). Falling back.",
                        completion_time_s, energy_consumed_pct,
                    )
                    completion_time_s, energy_consumed_pct = self._deterministic(
                        route_dist_km, battery_start_pct, payload_kg,
                        drone_speed_kmh, wind_speed_kmh, pad_queue_estimate,
                    )
                else:
                    used_model = True

            except Exception as exc:
                logger.error("MissionCostPredictor: inference error (%s). Falling back.", exc)
                completion_time_s, energy_consumed_pct = self._deterministic(
                    route_dist_km, battery_start_pct, payload_kg,
                    drone_speed_kmh, wind_speed_kmh, pad_queue_estimate,
                )
        else:
            completion_time_s, energy_consumed_pct = self._deterministic(
                route_dist_km, battery_start_pct, payload_kg,
                drone_speed_kmh, wind_speed_kmh, pad_queue_estimate,
            )

        # Feasibility: reject if expected energy consumption leaves less than reserve
        feasible = energy_consumed_pct <= (battery_start_pct - self.BATTERY_RESERVE_PCT)

        return PredictionResult(
            completion_time_s=round(completion_time_s, 2),
            energy_consumed_pct=round(energy_consumed_pct, 2),
            used_model=used_model,
            model_name=self._model_name if used_model else "deterministic_fallback",
            feasible=feasible,
        )

    def _deterministic(
        self,
        route_dist_km: float,
        battery_start_pct: float,
        payload_kg: float,
        drone_speed_kmh: float,
        wind_speed_kmh: float,
        pad_queue_estimate: int,
    ) -> tuple[float, float]:
        """
        Deterministic fallback using same physics as simulation_engine.py.
        Used when the model is unavailable or produces implausible output.
        """
        payload_factor = 1.0 + (payload_kg / 5.0) * 0.3
        wind_factor = 1.0 + (wind_speed_kmh / 50.0) * 0.6
        wh_km = _BASE_WH_KM * payload_factor * wind_factor

        outbound_s = (route_dist_km / max(drone_speed_kmh, 1.0)) * 3600.0
        return_s = (route_dist_km / max(drone_speed_kmh, 1.0)) * 3600.0
        pad_wait_s = pad_queue_estimate * _PAD_WAIT_PER_BUSY_PAD_S
        completion_time_s = outbound_s + return_s + pad_wait_s + _SWAP_TIME_S

        outbound_energy = route_dist_km * wh_km
        return_energy = route_dist_km * _BASE_WH_KM
        energy_consumed_pct = outbound_energy + return_energy

        return completion_time_s, min(energy_consumed_pct, battery_start_pct)

    def status(self) -> dict:
        """Return model status information for the frontend model-info panel."""
        return {
            "model_available": self.model_available,
            "model_name": self._model_name,
            "model_path": str(MODEL_FILE) if MODEL_FILE.exists() else None,
            "battery_reserve_pct": self.BATTERY_RESERVE_PCT,
            "feature_names": [
                "route_dist_km", "battery_start_pct", "battery_soh_pct",
                "payload_kg", "drone_speed_kmh", "wind_speed_kmh",
                "weather_severity", "num_active_drones", "pad_queue_estimate",
                "priority_ordinal", "motor_hours", "alt_segment_ratio",
            ],
            "label_names": ["completion_time_s", "energy_consumed_pct"],
            "note": (
                "Trained on simulator-generated data. "
                "Real-world accuracy unvalidated. "
                "Hard safety constraints enforced by dispatcher, not ML model."
            ),
        }


# Singleton for use in dispatching
_predictor: MissionCostPredictor | None = None


def get_predictor() -> MissionCostPredictor:
    global _predictor
    if _predictor is None:
        _predictor = MissionCostPredictor()
    return _predictor
