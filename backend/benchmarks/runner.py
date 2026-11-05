"""
SkyGrid Benchmarks — Experiment Runner
==========================================
Runs controlled comparisons between three dispatch strategies:

  A. BASELINE  — nearest-eligible drone, shortest path, FIFO pad scheduling
  B. SKYGRID   — existing rule-based scoring (SoH, charge, payload, depot match)
  C. AI_ASSIST — SkyGrid scoring informed by ML cost predictions

All three strategies use identical:
  - Initial conditions (same fleet, depots, orders)
  - Hard safety constraints
  - Random seeds
  - Weather and pad-failure conditions

Usage:
    python -m backend.benchmarks.runner --scenarios 20 --fleet-size 6 --seed 42

Outputs (appended per run):
    results/benchmark_summary.csv
    results/benchmark_details.csv
    results/experiment_config.json

IMPORTANT: Results are from simulation only. They cannot be used to claim
real-world superiority without independent real-world validation.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import random
import sys
import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend/
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # project root
from services.simulation_engine import (
    Depot, Drone, DroneStatus, LandingPad, Order, OrderPriority,
    OrderStatus, PadStatus, Position, SimulationEngine,
)
from services.routing_service import RoutingService
from ml.predictor import get_predictor

logger = logging.getLogger(__name__)

RESULTS_DIR = Path(__file__).resolve().parents[2] / "results"


# ── Strategy enum ─────────────────────────────────────────────────────────────

class Strategy(str, Enum):
    BASELINE = "baseline"
    SKYGRID = "skygrid"
    AI_ASSIST = "ai_assist"


# ── Episode result ────────────────────────────────────────────────────────────

@dataclass
class EpisodeResult:
    episode_id: str
    strategy: str
    seed: int
    fleet_size: int
    n_orders: int
    scenario_tag: str
    # Outcome metrics
    n_delivered: int = 0
    n_failed: int = 0
    total_completion_time_s: float = 0.0
    mean_completion_time_s: float = 0.0
    p95_completion_time_s: float = 0.0
    total_energy_consumed_pct: float = 0.0
    energy_per_delivery_pct: float = 0.0
    mean_pad_wait_s: float = 0.0
    n_diversions: int = 0
    n_separation_violations: int = 0
    n_battery_reserve_violations: int = 0
    delivery_rate: float = 0.0
    sim_time_s: float = 0.0          # wall-clock time for simulation
    decision_latency_ms: float = 0.0  # time for dispatch decisions
    ml_predictions_made: int = 0
    ml_fallbacks: int = 0


# ── Scenario generator ────────────────────────────────────────────────────────

def _make_orders(
    n: int, depots: list[Depot], seed: int, priority_mix: dict | None = None
) -> list[Order]:
    """Generate n delivery orders with reproducible random positions."""
    rng = random.Random(seed)
    if priority_mix is None:
        priority_mix = {
            OrderPriority.STANDARD: 0.6,
            OrderPriority.EXPRESS: 0.2,
            OrderPriority.CRITICAL: 0.1,
            OrderPriority.MEDICAL: 0.1,
        }

    priorities = list(priority_mix.keys())
    weights = list(priority_mix.values())

    orders = []
    for i in range(n):
        depot = rng.choice(depots)
        lat = depot.position.lat + rng.uniform(-0.05, 0.05)
        lon = depot.position.lon + rng.uniform(-0.05, 0.05)
        priority = rng.choices(priorities, weights=weights, k=1)[0]
        weight_kg = rng.uniform(0.5, 8.0)
        sla_min = 12 if priority == OrderPriority.MEDICAL else (15 if priority == OrderPriority.CRITICAL else 30)

        orders.append(Order(
            id=f"ORD-{i:04d}",
            origin_depot=depot.id,
            destination=Position(round(lat, 5), round(lon, 5), 0),
            destination_label=f"Location-{i:04d}",
            weight_kg=round(weight_kg, 2),
            priority=priority,
            status=OrderStatus.QUEUED,
            sla_minutes=sla_min,
        ))
    return orders


# ── Dispatch strategies ───────────────────────────────────────────────────────

def _select_drone_baseline(
    engine: SimulationEngine, order: Order, routing: RoutingService
) -> Drone | None:
    """
    Baseline strategy:
    - Nearest eligible drone (by Euclidean proximity to depot)
    - Battery gate: charge > 30% AND estimated route cost + 20% reserve
    - FIFO ordering within eligible set
    """
    origin = engine.depots.get(order.origin_depot)
    if not origin:
        return None

    best_drone = None
    best_dist = float("inf")

    for drone in engine.drones.values():
        if drone.status != DroneStatus.IDLE:
            continue
        if drone.max_payload_kg < order.weight_kg:
            continue

        route_dist = drone.position.distance_to(order.destination)
        est_cost = routing.estimate_route_battery_cost(
            drone.position, order.destination, order.weight_kg
        )
        # Safety gate: ensure enough battery for round trip + reserve
        if drone.battery_charge < est_cost * 2 + 20.0:
            continue

        dist_to_depot = drone.position.distance_to(origin.position)
        if dist_to_depot < best_dist:
            best_dist = dist_to_depot
            best_drone = drone

    return best_drone


def _select_drone_skygrid(
    engine: SimulationEngine, order: Order, routing: RoutingService
) -> Drone | None:
    """
    SkyGrid strategy: composite scoring (SoH, charge, payload efficiency, depot match).
    Reuses existing DispatcherAgent logic.
    """
    from agents.dispatcher import DispatcherAgent
    dispatcher = DispatcherAgent(engine)
    ranked = dispatcher.rank_drones_for_order(order)
    return ranked[0][0] if ranked else None


def _select_drone_ai_assist(
    engine: SimulationEngine, order: Order, routing: RoutingService,
    predictor, stats: dict,
) -> Drone | None:
    """
    AI-assisted strategy:
    - Uses trained ML model to predict completion time and energy.
    - Ranks candidates by predicted completion_time_s (lower = preferred).
    - Hard safety constraints enforced before accepting any assignment.
    - Falls back to SkyGrid strategy if model unavailable or all infeasible.
    """
    origin = engine.depots.get(order.origin_depot)
    if not origin:
        return None

    candidates: list[tuple[Drone, float]] = []  # (drone, predicted_completion_time)

    active_count = sum(
        1 for d in engine.drones.values()
        if d.status not in (DroneStatus.IDLE, DroneStatus.BATTERY_SWAP)
    )
    pad_busy = sum(
        1 for depot in engine.depots.values()
        for pad in depot.pads if pad.status != PadStatus.AVAILABLE
    )
    priority_ordinal = {
        OrderPriority.STANDARD: 0,
        OrderPriority.EXPRESS: 1,
        OrderPriority.CRITICAL: 2,
        OrderPriority.MEDICAL: 3,
    }.get(order.priority, 0)

    for drone in engine.drones.values():
        if drone.status != DroneStatus.IDLE:
            continue
        if drone.max_payload_kg < order.weight_kg:
            continue

        route_dist = origin.position.distance_to(order.destination)

        t0 = time.perf_counter()
        result = predictor.predict(
            route_dist_km=route_dist,
            battery_start_pct=drone.battery_charge,
            battery_soh_pct=drone.battery_soh,
            payload_kg=order.weight_kg,
            drone_speed_kmh=drone.speed_kmh,
            wind_speed_kmh=12.0,  # default; real-time weather injected in Phase 7
            weather_severity=0.0,
            num_active_drones=active_count,
            pad_queue_estimate=pad_busy,
            priority_ordinal=priority_ordinal,
            motor_hours=drone.motor_hours,
            alt_segment_ratio=0.7,
        )
        latency_ms = (time.perf_counter() - t0) * 1000
        stats["total_latency_ms"] = stats.get("total_latency_ms", 0.0) + latency_ms
        stats["n_predictions"] = stats.get("n_predictions", 0) + 1

        if result.used_model:
            stats["ml_used"] = stats.get("ml_used", 0) + 1
        else:
            stats["ml_fallback"] = stats.get("ml_fallback", 0) + 1

        if result.feasible:
            candidates.append((drone, result.completion_time_s))

    if not candidates:
        # Fall back to SkyGrid strategy
        return _select_drone_skygrid(engine, order, routing)

    # Rank by predicted completion time
    candidates.sort(key=lambda x: x[1])
    return candidates[0][0]


# ── Episode simulation ────────────────────────────────────────────────────────

def run_episode(
    orders: list[Order],
    strategy: Strategy,
    seed: int,
    max_ticks: int = 2000,
    dt: float = 0.5,
) -> EpisodeResult:
    """
    Run one experiment episode and return metrics.

    The simulation advances until all orders are resolved or max_ticks reached.
    Failed orders (undelivered at max_ticks) are counted separately.
    """
    engine = SimulationEngine()
    routing = RoutingService()
    predictor = get_predictor()

    # Reset with the same initial state for all strategies
    engine.reset_simulation()

    # Inject orders
    for order in orders:
        engine.orders[order.id] = Order(
            id=order.id,
            origin_depot=order.origin_depot,
            destination=order.destination,
            destination_label=order.destination_label,
            weight_kg=order.weight_kg,
            priority=order.priority,
            status=OrderStatus.QUEUED,
            sla_minutes=order.sla_minutes,
        )

    dispatch_stats: dict = {}
    completion_times: list[float] = []
    pad_waits: list[float] = []
    energy_totals: list[float] = []
    n_diversions = 0

    dispatched_at: dict[str, float] = {}  # order_id -> tick when dispatched
    decision_latencies: list[float] = []

    sim_wall_start = time.perf_counter()

    for tick in range(max_ticks):
        sim_time_s = tick * dt

        # Dispatch queued orders
        queued = [o for o in engine.orders.values() if o.status == OrderStatus.QUEUED]

        # Sort by priority (medical first)
        queued.sort(key=lambda o: (
            0 if o.priority == OrderPriority.MEDICAL else
            1 if o.priority == OrderPriority.CRITICAL else
            2 if o.priority == OrderPriority.EXPRESS else 3,
            o.created_at,
        ))

        for order in queued:
            t0 = time.perf_counter()
            if strategy == Strategy.BASELINE:
                drone = _select_drone_baseline(engine, order, routing)
            elif strategy == Strategy.SKYGRID:
                drone = _select_drone_skygrid(engine, order, routing)
            else:  # AI_ASSIST
                drone = _select_drone_ai_assist(engine, order, routing, predictor, dispatch_stats)
            decision_latency = (time.perf_counter() - t0) * 1000
            decision_latencies.append(decision_latency)

            if drone:
                depot = engine.depots[order.origin_depot]
                engine._dispatch_drone(drone, order, depot)
                dispatched_at[order.id] = sim_time_s

        # Count diversions from this tick
        rerouting_before = sum(
            1 for d in engine.drones.values() if d.status == DroneStatus.REROUTING
        )

        # Advance simulation
        engine.tick(dt=dt)

        rerouting_after = sum(
            1 for d in engine.drones.values() if d.status == DroneStatus.REROUTING
        )
        n_diversions += max(0, rerouting_after - rerouting_before)

        # Check for newly delivered orders
        for order in engine.orders.values():
            if order.status == OrderStatus.DELIVERED and order.id not in dispatched_at:
                dispatched_at[order.id] = 0.0  # fallback
            if order.status == OrderStatus.DELIVERED:
                start = dispatched_at.get(order.id, 0.0)
                elapsed = sim_time_s - start
                if elapsed > 0:
                    completion_times.append(elapsed)

        # Early termination: all orders resolved
        active = [
            o for o in engine.orders.values()
            if o.status in (OrderStatus.QUEUED, OrderStatus.DISPATCHED, OrderStatus.IN_TRANSIT)
        ]
        if not active:
            break

    sim_wall_time = time.perf_counter() - sim_wall_start

    # Count outcomes
    n_delivered = sum(1 for o in engine.orders.values() if o.status == OrderStatus.DELIVERED)
    n_failed = len(orders) - n_delivered

    # Energy: sum of battery consumed (start - current) for all drones
    energy_per_drone = []
    for drone in engine.drones.values():
        # Find original spec charge (all start at 100%)
        consumed = 100.0 - drone.battery_charge
        if consumed > 0:
            energy_per_drone.append(consumed)

    energy_per_delivery = (
        sum(energy_per_drone) / max(n_delivered, 1)
    )

    mean_completion = (
        sum(completion_times) / max(len(completion_times), 1)
        if completion_times else 0.0
    )
    p95_completion = (
        float(sorted(completion_times)[int(0.95 * len(completion_times))])
        if completion_times else 0.0
    )

    mean_decision_latency = (
        sum(decision_latencies) / max(len(decision_latencies), 1)
        if decision_latencies else 0.0
    )

    return EpisodeResult(
        episode_id=str(uuid.uuid4())[:8],
        strategy=strategy.value,
        seed=seed,
        fleet_size=len(engine.drones),
        n_orders=len(orders),
        scenario_tag=f"n{len(orders)}_f{len(engine.drones)}_s{seed}",
        n_delivered=n_delivered,
        n_failed=n_failed,
        total_completion_time_s=sum(completion_times),
        mean_completion_time_s=round(mean_completion, 2),
        p95_completion_time_s=round(p95_completion, 2),
        total_energy_consumed_pct=round(sum(energy_per_drone), 2),
        energy_per_delivery_pct=round(energy_per_delivery, 2),
        mean_pad_wait_s=0.0,   # simplified; full queue tracking in Phase 6
        n_diversions=n_diversions,
        n_separation_violations=engine._separation_violations,
        n_battery_reserve_violations=0,
        delivery_rate=round(n_delivered / max(len(orders), 1), 4),
        sim_time_s=round(sim_wall_time, 3),
        decision_latency_ms=round(mean_decision_latency, 3),
        ml_predictions_made=dispatch_stats.get("n_predictions", 0),
        ml_fallbacks=dispatch_stats.get("ml_fallback", 0),
    )


# ── Experiment batch runner ───────────────────────────────────────────────────

def run_batch(
    n_scenarios: int = 10,
    n_orders: int = 5,
    seeds: list[int] | None = None,
    strategies: list[Strategy] | None = None,
) -> list[EpisodeResult]:
    """
    Run a batch of experiments across all strategies with the same scenarios.
    Ensures fair comparison: identical orders and seeds for each strategy.
    """
    if strategies is None:
        strategies = list(Strategy)
    if seeds is None:
        seeds = list(range(n_scenarios))

    engine = SimulationEngine()
    depots = list(engine.depots.values())

    all_results: list[EpisodeResult] = []

    for seed in seeds[:n_scenarios]:
        orders = _make_orders(n_orders, depots, seed=seed)
        for strategy in strategies:
            logger.info("Running episode: strategy=%s seed=%d orders=%d", strategy.value, seed, n_orders)
            result = run_episode(orders, strategy, seed=seed)
            all_results.append(result)
            logger.info(
                "  Result: delivered=%d/%d rate=%.1f%% energy/del=%.1f%% "
                "mean_time=%.0fs sep_violations=%d",
                result.n_delivered, result.n_orders,
                result.delivery_rate * 100,
                result.energy_per_delivery_pct,
                result.mean_completion_time_s,
                result.n_separation_violations,
            )

    return all_results


# ── CSV export ────────────────────────────────────────────────────────────────

def _result_as_dict(r: EpisodeResult) -> dict:
    return asdict(r)


def save_results(results: list[EpisodeResult], config: dict) -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    # Detailed results
    details_path = RESULTS_DIR / "benchmark_details.csv"
    fieldnames = list(_result_as_dict(results[0]).keys()) if results else []
    with open(details_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in results:
            writer.writerow(_result_as_dict(r))

    # Summary: mean metrics per strategy
    import statistics
    summary_rows = []
    for strategy in Strategy:
        subset = [r for r in results if r.strategy == strategy.value]
        if not subset:
            continue
        row = {
            "strategy": strategy.value,
            "n_episodes": len(subset),
            "mean_delivery_rate": round(statistics.mean(r.delivery_rate for r in subset), 4),
            "mean_completion_time_s": round(statistics.mean(r.mean_completion_time_s for r in subset), 2),
            "mean_energy_per_delivery": round(statistics.mean(r.energy_per_delivery_pct for r in subset), 2),
            "mean_diversions": round(statistics.mean(r.n_diversions for r in subset), 2),
            "mean_sep_violations": round(statistics.mean(r.n_separation_violations for r in subset), 2),
            "mean_decision_latency_ms": round(statistics.mean(r.decision_latency_ms for r in subset), 3),
        }
        summary_rows.append(row)

    summary_path = RESULTS_DIR / "benchmark_summary.csv"
    if summary_rows:
        with open(summary_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(summary_rows[0].keys()))
            writer.writeheader()
            writer.writerows(summary_rows)

    # Config
    config_path = RESULTS_DIR / "experiment_config.json"
    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)

    logger.info("Saved results to %s", RESULTS_DIR)
    print(f"\n[benchmark] Results saved to {RESULTS_DIR}")
    print(f"  Summary: {summary_path}")
    print(f"  Details: {details_path}")
    print(f"  Config:  {config_path}")
    print("\nStrategy comparison:")
    for row in summary_rows:
        print(
            f"  {row['strategy']:12s} | delivery_rate={row['mean_delivery_rate']:.1%} "
            f"| energy/del={row['mean_energy_per_delivery']:.1f}% "
            f"| mean_time={row['mean_completion_time_s']:.0f}s "
            f"| latency={row['mean_decision_latency_ms']:.1f}ms"
        )


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="SkyGrid Benchmark Runner")
    parser.add_argument("--scenarios", type=int, default=10, help="Number of test scenarios")
    parser.add_argument("--orders", type=int, default=5, help="Orders per scenario")
    parser.add_argument("--seed", type=int, default=42, help="Base random seed")
    parser.add_argument(
        "--strategies", nargs="+",
        choices=["baseline", "skygrid", "ai_assist"],
        default=["baseline", "skygrid", "ai_assist"],
    )
    args = parser.parse_args()

    strategies = [Strategy(s) for s in args.strategies]
    seeds = list(range(args.seed, args.seed + args.scenarios))

    config = {
        "n_scenarios": args.scenarios,
        "n_orders": args.orders,
        "base_seed": args.seed,
        "strategies": [s.value for s in strategies],
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "note": "Simulation-only results; not validated on physical hardware.",
    }

    print(f"[benchmark] Running {args.scenarios} scenarios × {len(strategies)} strategies...")
    results = run_batch(
        n_scenarios=args.scenarios,
        n_orders=args.orders,
        seeds=seeds,
        strategies=strategies,
    )
    save_results(results, config)


if __name__ == "__main__":
    main()
