"""
Fleet Dispatcher Agent
=======================
Asset Allocation & Triangular Routing optimization.
Evaluates fleet health, assigns drones, implements milk-run optimization.

Defect fix applied:
  D-006: Pre-flight battery feasibility check now compares available charge
         against estimated route consumption before accepting an assignment.
"""

from services.simulation_engine import (
    SimulationEngine, Drone, Order, DroneStatus, OrderPriority, OrderStatus, Position
)
# Approximate battery consumption per km at base conditions (Wh/km as % points)
_BASE_WH_KM = 2.8
_RESERVE_BUFFER_PCT = 20.0  # keep 20% battery reserve on arrival


class DispatcherAgent:
    """
    Fleet Dispatcher Agent — handles order ingestion, drone assignment,
    and triangular (milk-run) routing optimization.
    """

    AGENT_NAME = "DISPATCHER"

    def __init__(self, engine: SimulationEngine):
        self.engine = engine

    def evaluate_fleet_readiness(self) -> list[dict]:
        """Evaluate all drones and report fleet readiness."""
        logs = []
        idle_count = sum(1 for d in self.engine.drones.values() if d.status == DroneStatus.IDLE)
        active_count = sum(1 for d in self.engine.drones.values() if d.status != DroneStatus.IDLE)

        avg_soh = sum(d.battery_soh for d in self.engine.drones.values()) / max(
            len(self.engine.drones), 1
        )
        low_soh = [d for d in self.engine.drones.values() if d.battery_soh < 85]

        log = self.engine.emit_log(
            self.AGENT_NAME,
            f"📊 Fleet Readiness Report: {idle_count} idle, {active_count} active. "
            f"Avg SoH: {avg_soh:.1f}%. "
            f"{'⚠️ ' + str(len(low_soh)) + ' drones below 85% SoH threshold.' if low_soh else '✅ All drones above SoH threshold.'}",
        )
        logs.append(log)

        return logs

    def rank_drones_for_order(self, order: Order) -> list[tuple[Drone, float]]:
        """
        Rank available drones for an order by composite score:
        - SoH weight (higher is better)
        - Battery charge weight
        - Payload capacity match
        - Depot proximity

        D-006: only drones with sufficient battery to complete the route
               (plus RESERVE_BUFFER_PCT) are included as candidates.
        """
        candidates = []

        # Estimate one-way distance for battery feasibility
        origin_depot = self.engine.depots.get(order.origin_depot)
        if origin_depot:
            route_dist_km = origin_depot.position.distance_to(order.destination)
        else:
            route_dist_km = 0.0

        # Estimated consumption: outbound + return (with payload factor)
        payload_factor = 1.0 + (order.weight_kg / 5.0) * 0.3
        min_battery_needed = (
            route_dist_km * _BASE_WH_KM * payload_factor  # outbound
            + route_dist_km * _BASE_WH_KM  # return (no payload)
            + _RESERVE_BUFFER_PCT
        )

        for drone in self.engine.drones.values():
            if drone.status != DroneStatus.IDLE:
                continue
            if drone.max_payload_kg < order.weight_kg:
                continue
            # D-006: battery feasibility gate
            if drone.battery_charge < max(30.0, min_battery_needed):
                continue

            # Score calculation
            soh_score = drone.battery_soh / 100.0
            charge_score = drone.battery_charge / 100.0
            payload_eff = 1.0 - abs(drone.max_payload_kg - order.weight_kg) / drone.max_payload_kg
            depot_match = 1.0 if drone.home_depot == order.origin_depot else 0.5

            # Priority bonus for medical/critical
            priority_mult = 1.0
            if order.priority == OrderPriority.MEDICAL:
                priority_mult = 1.5
            elif order.priority == OrderPriority.CRITICAL:
                priority_mult = 1.3

            score = (soh_score * 0.3 + charge_score * 0.3 + payload_eff * 0.2 + depot_match * 0.2) * priority_mult
            candidates.append((drone, score))

        candidates.sort(key=lambda x: x[1], reverse=True)
        return candidates

    def check_triangular_opportunity(self, drone: Drone, delivery_pos: Position) -> str | None:
        """
        Check if any secondary depot near the delivery point has queued
        outbound orders, enabling a triangular milk-run instead of deadhead return.
        """
        home_depot = self.engine.depots.get(drone.home_depot)
        if not home_depot:
            return None

        best_depot_id = None
        best_savings = 0.0

        for depot_id, depot in self.engine.depots.items():
            if depot_id == drone.home_depot:
                continue
            if not depot.queued_outbound:
                continue

            # Calculate savings: deadhead vs triangular
            deadhead_dist = delivery_pos.distance_to(home_depot.position)
            tri_dist = delivery_pos.distance_to(depot.position)

            if tri_dist < deadhead_dist:
                savings = deadhead_dist - tri_dist
                if savings > best_savings:
                    best_savings = savings
                    best_depot_id = depot_id

        return best_depot_id
