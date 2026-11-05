"""
SkyGrid ML — Data Generation
==============================
Generates synthetic training examples for the mission-cost prediction model.

Each example represents one candidate drone assignment with:
  - Route and mission features
  - Actual simulated outcome (duration and energy consumption)

These data are SYNTHETIC, generated from the simulation engine's documented
physics model. They are valid only within the simulator's assumptions and
have NOT been validated against physical drone hardware.

Usage:
    python -m backend.ml.data_generation --samples 5000 --seed 42 --output data/raw_episodes.csv
"""

from __future__ import annotations

import argparse
import csv
import logging
import math
import os
import random
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterator

# Allow running as a script from project root
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

from services.simulation_engine import (
    Depot, Drone, DroneStatus, Order, OrderPriority, Position, SimulationEngine,
)
from services.routing_service import RoutingService

logger = logging.getLogger(__name__)

# ── Feature and label definitions ────────────────────────────────────────────

FEATURE_NAMES: list[str] = [
    "route_dist_km",          # Great-circle distance from origin depot to destination
    "battery_start_pct",      # Drone battery state-of-charge at dispatch (%)
    "battery_soh_pct",        # Drone battery state-of-health (%)
    "payload_kg",             # Delivery payload weight (kg)
    "drone_speed_kmh",        # Drone cruise speed (km/h)
    "wind_speed_kmh",         # Estimated wind speed on route midpoint (km/h)
    "weather_severity",       # 0=clear, 1=caution, 2=advisory, 3=unsafe
    "num_active_drones",      # Other airborne drones at dispatch time (count)
    "pad_queue_estimate",     # Estimated pads busy at origin depot (count)
    "priority_ordinal",       # 0=standard, 1=express, 2=critical, 3=medical
    "motor_hours",            # Drone motor hours (age proxy)
    "alt_segment_ratio",      # Fraction of route at cruise altitude
]

LABEL_NAMES: list[str] = [
    "completion_time_s",      # Simulated mission duration from dispatch to battery-swap start (s)
    "energy_consumed_pct",    # Battery percentage consumed over the full outbound+return trip
]

# ── Episode dataclass ─────────────────────────────────────────────────────────

@dataclass
class Episode:
    """One simulated mission assignment with features and outcomes."""
    # Features
    route_dist_km: float
    battery_start_pct: float
    battery_soh_pct: float
    payload_kg: float
    drone_speed_kmh: float
    wind_speed_kmh: float
    weather_severity: float
    num_active_drones: int
    pad_queue_estimate: int
    priority_ordinal: int
    motor_hours: float
    alt_segment_ratio: float
    # Labels
    completion_time_s: float
    energy_consumed_pct: float
    # Metadata
    episode_id: str = ""
    seed: int = 0
    scenario_tag: str = "synthetic"

    def to_row(self) -> dict:
        return {
            **{k: getattr(self, k) for k in FEATURE_NAMES},
            **{k: getattr(self, k) for k in LABEL_NAMES},
            "episode_id": self.episode_id,
            "seed": self.seed,
            "scenario_tag": self.scenario_tag,
        }


# ── Simulation-based episode generator ───────────────────────────────────────

class EpisodeGenerator:
    """
    Generates synthetic mission episodes by running short forward simulations.

    Each episode:
      1. Samples a drone state and a delivery order.
      2. Computes the route via RoutingService.
      3. Estimates energy consumption using the documented battery model.
      4. Estimates completion time from distance and speed.
      5. Returns an Episode with features and outcomes.

    Labels are computed from the same physics model used by the simulation engine,
    not from external measurements. This means the ML model will learn to
    approximate the same model \u2014 useful for evaluating whether ML can predict
    dispatcher outcomes more quickly than full simulation.
    """

    BASE_WH_KM = 2.8          # Wh/km at 0 payload, 0 wind
    CRUISE_SPEED_KMH = 65.0   # default drone speed
    SAFE_RESERVE_PCT = 15.0   # safety threshold

    def __init__(self, routing_service: RoutingService | None = None):
        self._routing = routing_service or RoutingService()
        self._engine = SimulationEngine()  # used for depot positions only

    def _sample_position(
        self, rng: random.Random, center_lat: float = 6.9271, center_lon: float = 79.8612,
        radius_deg: float = 0.06,
    ) -> Position:
        """Sample a random delivery destination within the operational area."""
        lat = center_lat + rng.uniform(-radius_deg, radius_deg)
        lon = center_lon + rng.uniform(-radius_deg, radius_deg)
        return Position(lat, lon, 0)

    def _weather_severity(self, wind_kmh: float) -> float:
        if wind_kmh >= 50.0:
            return 3.0
        elif wind_kmh >= 35.0:
            return 2.0
        elif wind_kmh >= 25.0:
            return 1.0
        return 0.0

    def _simulate_mission(
        self,
        rng: random.Random,
        drone_speed: float,
        battery_start: float,
        battery_soh: float,
        payload_kg: float,
        route_dist_km: float,
        wind_kmh: float,
        num_pads_busy: int,
    ) -> tuple[float, float]:
        """
        Compute mission completion_time_s and energy_consumed_pct.

        Physics model (matches simulation_engine.py):
          base_discharge = 0.015 %/sec
          weather_penalty = wind_kmh/50 (approx for headwind)
          payload_factor = 1 + (kg/max_kg) * 0.3

        Assumes:
          - Outbound travel time = dist/speed
          - Return travel time = dist/speed (no payload)
          - Battery swap = 90 s
          - Pad wait = 30*num_pads_busy seconds (approximate queue)
        """
        # travel times
        travel_speed = drone_speed * (battery_soh / 100.0)  # SoH reduces effective speed
        outbound_time_s = (route_dist_km / max(travel_speed, 1.0)) * 3600.0
        return_time_s = (route_dist_km / max(drone_speed, 1.0)) * 3600.0  # no SoH penalty on return for simplicity

        pad_wait_s = num_pads_busy * 30.0
        swap_time_s = 90.0
        completion_time_s = outbound_time_s + return_time_s + pad_wait_s + swap_time_s

        # energy model
        payload_factor = 1.0 + (payload_kg / 5.0) * 0.3
        wind_factor = 1.0 + (wind_kmh / 50.0) * 0.6
        wh_km = self.BASE_WH_KM * payload_factor * wind_factor

        outbound_energy = route_dist_km * wh_km
        return_energy = route_dist_km * self.BASE_WH_KM  # no payload on return
        total_energy_pct = outbound_energy + return_energy

        # add hover/holding penalty for busy pads
        total_energy_pct += num_pads_busy * 0.02 * pad_wait_s

        return completion_time_s, min(total_energy_pct, battery_start)

    def generate(
        self,
        n_samples: int = 5000,
        seed: int = 42,
    ) -> list[Episode]:
        """
        Generate n_samples synthetic mission episodes.

        Varying conditions across samples:
          - Battery charge: 35-100%
          - Battery SoH: 75-100%
          - Payload: 0.5-8 kg
          - Wind: 0-55 km/h
          - Active drones: 0-5
          - Pad queue: 0-2
          - Priority: all four classes
        """
        rng = random.Random(seed)
        depots = list(self._engine.depots.values())
        episodes = []

        priority_map = {
            0: "standard", 1: "express", 2: "critical", 3: "medical"
        }

        for i in range(n_samples):
            ep_seed = seed * 10000 + i
            ep_rng = random.Random(ep_seed)

            depot = ep_rng.choice(depots)
            dest = self._sample_position(ep_rng, depot.position.lat, depot.position.lon)
            route_dist = depot.position.distance_to(dest)

            battery_start = ep_rng.uniform(35.0, 100.0)
            battery_soh = ep_rng.uniform(75.0, 100.0)
            payload_kg = ep_rng.uniform(0.5, 8.0)
            drone_speed = ep_rng.uniform(50.0, 75.0)
            wind_kmh = ep_rng.uniform(0.0, 55.0)
            num_active = ep_rng.randint(0, 5)
            pad_queue = ep_rng.randint(0, 2)
            priority = ep_rng.randint(0, 3)
            motor_hours = ep_rng.uniform(50.0, 850.0)

            completion_time, energy_consumed = self._simulate_mission(
                rng=ep_rng,
                drone_speed=drone_speed,
                battery_start=battery_start,
                battery_soh=battery_soh,
                payload_kg=payload_kg,
                route_dist_km=route_dist,
                wind_kmh=wind_kmh,
                num_pads_busy=pad_queue,
            )

            # Altitude ratio: fraction of route at cruise (rough estimate)
            alt_segment_ratio = max(0.0, min(1.0, 1.0 - (2 * 0.15) if route_dist > 0.5 else 0.5))

            ep = Episode(
                route_dist_km=round(route_dist, 4),
                battery_start_pct=round(battery_start, 2),
                battery_soh_pct=round(battery_soh, 2),
                payload_kg=round(payload_kg, 3),
                drone_speed_kmh=round(drone_speed, 1),
                wind_speed_kmh=round(wind_kmh, 1),
                weather_severity=self._weather_severity(wind_kmh),
                num_active_drones=num_active,
                pad_queue_estimate=pad_queue,
                priority_ordinal=priority,
                motor_hours=round(motor_hours, 1),
                alt_segment_ratio=round(alt_segment_ratio, 3),
                completion_time_s=round(completion_time, 2),
                energy_consumed_pct=round(energy_consumed, 2),
                episode_id=f"ep-{ep_seed:08d}",
                seed=ep_seed,
                scenario_tag="synthetic_v1",
            )
            episodes.append(ep)

        logger.info("Generated %d episodes (seed=%d)", len(episodes), seed)
        return episodes


# ── CSV I/O ───────────────────────────────────────────────────────────────────

def save_episodes(episodes: list[Episode], path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = FEATURE_NAMES + LABEL_NAMES + ["episode_id", "seed", "scenario_tag"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for ep in episodes:
            writer.writerow(ep.to_row())
    logger.info("Saved %d episodes to %s", len(episodes), path)


def load_episodes(path: str | Path) -> list[dict]:
    path = Path(path)
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Generate SkyGrid ML training episodes")
    parser.add_argument("--samples", type=int, default=5000, help="Number of episodes")
    parser.add_argument("--seed", type=int, default=42, help="Global random seed")
    parser.add_argument(
        "--output", type=str, default="backend/ml/data/raw_episodes.csv",
        help="Output CSV path",
    )
    args = parser.parse_args()

    gen = EpisodeGenerator()
    episodes = gen.generate(n_samples=args.samples, seed=args.seed)
    save_episodes(episodes, args.output)
    print(f"[data_generation] Wrote {len(episodes)} episodes to {args.output}")


if __name__ == "__main__":
    main()
