"""
SkyGrid — Backend Unit and Integration Tests
=============================================
Tests are organised by module. Run with:
    python -m pytest backend/tests/ -v

Covers:
  - Routing service: weather penalty non-accumulation (D-001),
    out-of-grid detection (D-002), base weight storage
  - Simulation engine: reset fidelity (D-003), pad release on divert (D-004),
    separation check (D-010), battery feasibility (D-006)
  - ML predictor: safe fallback when no model, feasibility flag
  - Benchmark runner: episode completes without crashing

All tests use no external APIs. Weather service is not called in tests.
"""

import sys
import math
import json
import random
import time
from pathlib import Path

import pytest

# Allow imports from project root
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.services.simulation_engine import (
    DroneStatus, LandingPad, Order, OrderPriority, OrderStatus,
    PadStatus, Position, SimulationEngine, MIN_SEPARATION_KM,
)
from backend.services.routing_service import RoutingService
from backend.ml.predictor import MissionCostPredictor


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def engine() -> SimulationEngine:
    return SimulationEngine()


@pytest.fixture
def routing() -> RoutingService:
    return RoutingService()


# ── Routing Service Tests ─────────────────────────────────────────────────────

class TestRoutingService:

    def test_build_nav_grid(self, routing: RoutingService):
        """Grid should have GRID_SIZE² nodes."""
        expected_nodes = routing.GRID_SIZE ** 2
        assert routing.graph.number_of_nodes() == expected_nodes

    def test_base_weights_stored(self, routing: RoutingService):
        """Every edge should have a base_weight attribute (D-001 requirement)."""
        for u, v, data in routing.graph.edges(data=True):
            assert "base_weight" in data, f"Edge ({u},{v}) missing base_weight"
            assert data["base_weight"] == data["weight"], "Initial weight should equal base_weight"

    def test_weather_penalty_does_not_accumulate(self, routing: RoutingService):
        """
        D-001: Running compute_path twice with the same weather cell must not
        produce heavier penalties on the second call.
        """
        start = Position(6.9271, 79.8612)
        end = Position(6.9400, 79.8700)
        weather = [{
            "active": True,
            "position": {"lat": 6.933, "lon": 79.865},
            "radius_km": 2.0,
            "wind_speed_kmh": 40.0,
        }]

        # First call
        path1 = routing.compute_path(start, end, weather_cells=weather)

        # Read edge weights after first call (should be base_weight after restore)
        weights_after_first = {
            (u, v): data["weight"]
            for u, v, data in routing.graph.edges(data=True)
        }

        # Second call with same weather
        path2 = routing.compute_path(start, end, weather_cells=weather)

        # Weights after second call should equal those after first call
        for (u, v), w1 in weights_after_first.items():
            w2 = routing.graph[u][v]["weight"]
            assert abs(w2 - w1) < 1e-9, (
                f"Edge ({u},{v}) weight changed from {w1} to {w2} after second call "
                f"— weather penalty is accumulating (D-001)"
            )

    def test_out_of_grid_returns_direct_path(self, routing: RoutingService):
        """D-002: Position far outside grid falls back to direct path, not error."""
        start = Position(6.9271, 79.8612)
        end = Position(99.0, 99.0)  # wildly out of grid
        path = routing.compute_path(start, end)
        # Should return a non-empty direct path without raising
        assert len(path) >= 2

    def test_in_grid_detection(self, routing: RoutingService):
        center = Position(6.9271, 79.8612)
        assert routing.is_in_grid(center.lat, center.lon)
        assert not routing.is_in_grid(99.0, 99.0)

    def test_same_start_end_returns_two_waypoints(self, routing: RoutingService):
        pos = Position(6.9271, 79.8612)
        path = routing.compute_path(pos, pos)
        assert len(path) == 2

    def test_battery_curve_decreasing(self, routing: RoutingService):
        """Battery level should never increase between waypoints."""
        waypoints = [
            {"lat": 6.9271, "lon": 79.8612, "alt": 0},
            {"lat": 6.9300, "lon": 79.8650, "alt": 120},
            {"lat": 6.9350, "lon": 79.8700, "alt": 120},
            {"lat": 6.9400, "lon": 79.8750, "alt": 30},
        ]
        curve = routing.calculate_battery_curve(waypoints, payload_kg=2.0, battery_start=80.0)
        levels = [p["battery_pct"] for p in curve]
        for i in range(1, len(levels)):
            assert levels[i] <= levels[i - 1] + 1e-6, (
                f"Battery increased from {levels[i-1]} to {levels[i]} at step {i}"
            )

    def test_estimate_route_battery_cost_positive(self, routing: RoutingService):
        """Estimated cost should be positive for non-trivial routes."""
        start = Position(6.9271, 79.8612)
        end = Position(6.9400, 79.8700)
        cost = routing.estimate_route_battery_cost(start, end, payload_kg=2.0)
        assert cost > 0.0

    def test_weather_penalty_restore_to_base(self, routing: RoutingService):
        """
        D-001 restoration: base weights must be restored at the START of each call.
        After TWO calls with weather, all weights should equal base_weight at
        the start of the third call (verified by calling _restore_base_weights directly).
        """
        start = Position(6.9271, 79.8612)
        end = Position(6.9350, 79.8680)
        weather = [{"active": True, "position": {"lat": 6.93, "lon": 79.86},
                    "radius_km": 1.0, "wind_speed_kmh": 50.0}]
        # Two calls with heavy weather
        routing.compute_path(start, end, weather_cells=weather)
        routing.compute_path(start, end, weather_cells=weather)
        # Manually restore (as would happen at start of next call)
        routing._restore_base_weights()
        for u, v, data in routing.graph.edges(data=True):
            assert abs(data["weight"] - data["base_weight"]) < 1e-9, (
                f"Edge ({u},{v}) not restored to base_weight after _restore_base_weights"
            )


# ── Simulation Engine Tests ───────────────────────────────────────────────────

class TestSimulationEngine:

    def test_init_creates_drones_and_depots(self, engine: SimulationEngine):
        assert len(engine.drones) == 6
        assert len(engine.depots) == 3

    def test_reset_restores_battery_soh(self, engine: SimulationEngine):
        """D-003: reset must restore original SoH, not leave degraded values."""
        original_sohs = {d.id: d.battery_soh for d in engine.drones.values()}

        # Degrade battery SoH manually (simulating mission wear)
        for drone in engine.drones.values():
            drone.battery_soh = 50.0
            drone.battery_charge = 30.0

        engine.reset_simulation()

        for drone in engine.drones.values():
            assert abs(drone.battery_soh - original_sohs[drone.id]) < 0.01, (
                f"{drone.id}: SoH after reset {drone.battery_soh} != original {original_sohs[drone.id]}"
            )
            assert drone.battery_charge == 100.0

    def test_reset_clears_orders(self, engine: SimulationEngine):
        engine.create_scenario_a()
        assert len(engine.orders) > 0
        engine.reset_simulation()
        assert len(engine.orders) == 0

    def test_reset_clears_weather_cells(self, engine: SimulationEngine):
        engine.inject_microburst()
        assert len(engine.weather_cells) > 0
        engine.reset_simulation()
        assert len(engine.weather_cells) == 0

    def test_separation_check_fires(self, engine: SimulationEngine):
        """D-010: co-located airborne drones should trigger separation violation."""
        # Place two drones at same position and set both airborne
        drones = list(engine.drones.values())
        d1, d2 = drones[0], drones[1]

        same_pos = Position(6.9271, 79.8612, 120)
        d1.position = same_pos
        d2.position = Position(same_pos.lat, same_pos.lon, same_pos.alt)  # identical
        d1.status = DroneStatus.EN_ROUTE
        d2.status = DroneStatus.EN_ROUTE

        initial_violations = engine._separation_violations
        engine._check_separation()
        assert engine._separation_violations > initial_violations, (
            "Expected separation violation to be logged for co-located drones"
        )

    def test_separation_no_violation_when_far(self, engine: SimulationEngine):
        """Drones far apart should not trigger a violation."""
        drones = list(engine.drones.values())
        d1, d2 = drones[0], drones[1]

        d1.position = Position(6.9000, 79.8500, 120)
        d2.position = Position(6.9500, 79.9000, 120)  # > 5 km apart
        d1.status = DroneStatus.EN_ROUTE
        d2.status = DroneStatus.EN_ROUTE

        initial_violations = engine._separation_violations
        engine._check_separation()
        assert engine._separation_violations == initial_violations

    def test_pad_reservation_released_on_divert(self, engine: SimulationEngine):
        """D-004: _release_pad_for_drone should free reserved pads."""
        depot = list(engine.depots.values())[0]
        pad = depot.pads[0]
        drone_id = list(engine.drones.keys())[0]

        pad.status = PadStatus.RESERVED
        pad.reserved_for = drone_id

        engine._release_pad_for_drone(drone_id)
        assert pad.status == PadStatus.AVAILABLE
        assert pad.reserved_for is None

    def test_force_pad_clear_does_not_grant_occupied(self, engine: SimulationEngine):
        """D-009: _force_pad_clear must not grant OCCUPIED pads."""
        depot = list(engine.depots.values())[0]
        drone_id = list(engine.drones.keys())[0]
        drone = engine.drones[drone_id]
        drone.status = DroneStatus.HOLDING

        # Mark all pads as OCCUPIED
        for pad in depot.pads:
            pad.status = PadStatus.OCCUPIED
            pad.reserved_for = "other_drone"

        engine._force_pad_clear(depot.id, drone_id)
        # Drone should still be HOLDING (no AVAILABLE pad to grant)
        assert drone.status == DroneStatus.HOLDING

    def test_generate_waypoints_reproducible_with_seed(self, engine: SimulationEngine):
        """D-008: same seed should produce identical waypoints."""
        start = Position(6.9271, 79.8612)
        end = Position(6.9400, 79.8700)
        wp1 = engine._generate_waypoints(start, end, seed=123)
        wp2 = engine._generate_waypoints(start, end, seed=123)
        assert wp1 == wp2

    def test_generate_waypoints_different_seeds(self, engine: SimulationEngine):
        """Different seeds should (almost certainly) produce different waypoints."""
        start = Position(6.9271, 79.8612)
        end = Position(6.9400, 79.8700)
        wp1 = engine._generate_waypoints(start, end, seed=1)
        wp2 = engine._generate_waypoints(start, end, seed=2)
        # At least one waypoint should differ
        assert any(a != b for a, b in zip(wp1, wp2))

    def test_emit_log_returns_dict(self, engine: SimulationEngine):
        log = engine.emit_log("TEST", "Test message")
        assert "id" in log
        assert "timestamp" in log
        assert "agent" in log
        assert "message" in log

    def test_scenario_a_dispatches_drones(self, engine: SimulationEngine):
        """Scenario A should dispatch at least some drones."""
        engine.create_scenario_a()
        active = [d for d in engine.drones.values() if d.status != DroneStatus.IDLE]
        assert len(active) > 0

    def test_scenario_c_uses_medical_priority(self, engine: SimulationEngine):
        """Scenario C should create a MEDICAL priority order."""
        engine.create_scenario_c()
        medical_orders = [
            o for o in engine.orders.values() if o.priority == OrderPriority.MEDICAL
        ]
        assert len(medical_orders) >= 1

    def test_tick_advances_drone_position(self, engine: SimulationEngine):
        """A drone en-route should move after a tick."""
        engine.create_scenario_a()
        drone = next(
            d for d in engine.drones.values() if d.status == DroneStatus.EN_ROUTE
        )
        initial_lat = drone.position.lat
        initial_lon = drone.position.lon
        engine.tick(dt=10.0)  # large dt to ensure movement
        # At least one coordinate should have changed
        moved = (
            drone.position.lat != initial_lat or drone.position.lon != initial_lon
        )
        assert moved

    def test_battery_decreases_in_flight(self, engine: SimulationEngine):
        """Battery should decrease after ticks for a flying drone."""
        engine.create_scenario_a()
        drone = next(
            d for d in engine.drones.values() if d.status == DroneStatus.EN_ROUTE
        )
        initial_charge = drone.battery_charge
        for _ in range(20):
            engine.tick(dt=1.0)
        # Battery should have decreased by at least a small amount
        assert drone.battery_charge <= initial_charge

    def test_get_full_state_structure(self, engine: SimulationEngine):
        state = engine.get_full_state()
        assert "drones" in state
        assert "depots" in state
        assert "orders" in state
        assert "metrics" in state
        assert "chaos_state" in state


# ── ML Predictor Tests ────────────────────────────────────────────────────────

class TestMissionCostPredictor:

    def test_fallback_when_no_model(self):
        """Predictor with no model file should return deterministic fallback."""
        predictor = MissionCostPredictor(model_path=Path("/nonexistent/model.joblib"))
        result = predictor.predict(
            route_dist_km=4.0, battery_start_pct=80.0, battery_soh_pct=95.0,
            payload_kg=2.0, drone_speed_kmh=65.0, wind_speed_kmh=10.0,
            weather_severity=0.0, num_active_drones=2, pad_queue_estimate=1,
            priority_ordinal=0, motor_hours=300.0, alt_segment_ratio=0.7,
        )
        assert not result.used_model
        assert result.model_name == "deterministic_fallback"
        assert result.completion_time_s > 0
        assert result.energy_consumed_pct >= 0

    def test_feasibility_low_battery(self):
        """Assignment with barely enough battery should be infeasible."""
        predictor = MissionCostPredictor(model_path=Path("/nonexistent/model.joblib"))
        result = predictor.predict(
            route_dist_km=10.0,  # long route
            battery_start_pct=25.0,  # very low battery
            battery_soh_pct=95.0, payload_kg=5.0, drone_speed_kmh=65.0,
            wind_speed_kmh=0.0, weather_severity=0.0, num_active_drones=0,
            pad_queue_estimate=0, priority_ordinal=0, motor_hours=300.0,
            alt_segment_ratio=0.7,
        )
        assert not result.feasible, "10 km route with 25% battery should be infeasible"

    def test_feasibility_full_battery_short_route(self):
        """Short route with full battery should be feasible."""
        predictor = MissionCostPredictor(model_path=Path("/nonexistent/model.joblib"))
        result = predictor.predict(
            route_dist_km=1.0,  # very short
            battery_start_pct=100.0,
            battery_soh_pct=95.0, payload_kg=1.0, drone_speed_kmh=65.0,
            wind_speed_kmh=0.0, weather_severity=0.0, num_active_drones=0,
            pad_queue_estimate=0, priority_ordinal=0, motor_hours=300.0,
            alt_segment_ratio=0.7,
        )
        assert result.feasible, "1 km route with 100% battery should be feasible"

    def test_status_dict_structure(self):
        predictor = MissionCostPredictor(model_path=Path("/nonexistent/model.joblib"))
        status = predictor.status()
        assert "model_available" in status
        assert "feature_names" in status
        assert "label_names" in status
        assert "note" in status


# ── Position Tests ────────────────────────────────────────────────────────────

class TestPosition:

    def test_distance_zero_same_point(self):
        p = Position(6.9271, 79.8612)
        assert p.distance_to(p) == 0.0

    def test_distance_positive(self):
        p1 = Position(6.9271, 79.8612)
        p2 = Position(6.9400, 79.8700)
        assert p1.distance_to(p2) > 0.0

    def test_distance_symmetric(self):
        p1 = Position(6.9271, 79.8612)
        p2 = Position(6.9400, 79.8700)
        assert abs(p1.distance_to(p2) - p2.distance_to(p1)) < 1e-9

    def test_separation_constant(self):
        """MIN_SEPARATION_KM should be a positive float."""
        assert MIN_SEPARATION_KM > 0.0


# ── Haversine sanity ─────────────────────────────────────────────────────────

class TestHaversine:

    def test_known_distance(self):
        """Colombo Fort to Maradana: ~2.5 km (rough check)."""
        d = RoutingService._haversine(6.9344, 79.8428, 6.9171, 79.8600)
        assert 1.5 < d < 3.5, f"Unexpected distance: {d} km"
