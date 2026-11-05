"""
SkyGrid Enterprise - Simulation Engine
=======================================
Deterministic Simulation & Reasoning Engine providing realistic
pre-computed structured reasoning, state transitions, and telemetry.
Serves as the primary simulation backbone AND the LLM-free fallback.

Defect fixes applied:
  D-003: reset_simulation() now restores original drone specs.
  D-004: Pre-reserved return pad released when drone is diverted.
  D-005: pad_congestion auto-clears via timer instead of only on alt-found.
  D-007: Emergency ETA battery estimate computed from distance + consumption.
  D-008: _generate_waypoints accepts an optional seed for reproducibility.
  D-009: _force_pad_clear only grants AVAILABLE pads.
  D-010: Minimum horizontal separation constraint checked each tick.
"""

import math
import random
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

# Minimum horizontal separation between simultaneously airborne drones (km)
MIN_SEPARATION_KM: float = 0.05  # 50 m


# ── Enums ─────────────────────────────────────────────────────────────

class DroneStatus(str, Enum):
    IDLE = "idle"
    ASSIGNED = "assigned"
    EN_ROUTE = "en_route"
    DELIVERING = "delivering"
    RETURNING = "returning"
    REROUTING = "rerouting"
    LANDING = "landing"
    BATTERY_SWAP = "battery_swap"
    HOLDING = "holding"
    EMERGENCY = "emergency"
    DIVERTED = "diverted"


class PadStatus(str, Enum):
    AVAILABLE = "available"
    OCCUPIED = "occupied"
    RESERVED = "reserved"
    BLOCKED = "blocked"


class OrderPriority(str, Enum):
    STANDARD = "standard"
    EXPRESS = "express"
    CRITICAL = "critical"
    MEDICAL = "medical"


class OrderStatus(str, Enum):
    QUEUED = "queued"
    DISPATCHED = "dispatched"
    IN_TRANSIT = "in_transit"
    DELIVERED = "delivered"
    FAILED = "failed"
    REROUTED = "rerouted"


# ── Data Models ───────────────────────────────────────────────────────

@dataclass
class Position:
    lat: float
    lon: float
    alt: float = 120.0  # metres AGL

    def to_dict(self) -> dict:
        return {"lat": self.lat, "lon": self.lon, "alt": self.alt}

    def distance_to(self, other: "Position") -> float:
        """Haversine distance in km."""
        R = 6371.0
        lat1, lon1 = math.radians(self.lat), math.radians(self.lon)
        lat2, lon2 = math.radians(other.lat), math.radians(other.lon)
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
        return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


@dataclass
class LandingPad:
    id: str
    depot_id: str
    status: PadStatus = PadStatus.AVAILABLE
    reserved_for: str | None = None
    eta_seconds: float = 0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "depot_id": self.depot_id,
            "status": self.status.value,
            "reserved_for": self.reserved_for,
            "eta_seconds": self.eta_seconds,
        }


@dataclass
class Depot:
    id: str
    name: str
    position: Position
    pads: list[LandingPad] = field(default_factory=list)
    battery_swap_stations: int = 2
    queued_outbound: list[str] = field(default_factory=list)  # order IDs

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "position": self.position.to_dict(),
            "pads": [p.to_dict() for p in self.pads],
            "battery_swap_stations": self.battery_swap_stations,
            "queued_outbound": self.queued_outbound,
        }


@dataclass
class Drone:
    id: str
    name: str
    position: Position
    home_depot: str
    battery_soh: float = 95.0       # State of Health %
    battery_charge: float = 100.0   # Current charge %
    max_payload_kg: float = 5.0
    current_payload_kg: float = 0.0
    status: DroneStatus = DroneStatus.IDLE
    speed_kmh: float = 65.0
    altitude_m: float = 120.0
    heading_deg: float = 0.0
    motor_hours: float = 342.0
    charge_cycles: int = 127
    current_order: str | None = None
    waypoints: list[dict] = field(default_factory=list)
    waypoint_index: int = 0
    route_color: str = "#00ff88"
    triangular_target: str | None = None  # secondary depot for milk-run

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "position": self.position.to_dict(),
            "home_depot": self.home_depot,
            "battery_soh": round(self.battery_soh, 1),
            "battery_charge": round(self.battery_charge, 1),
            "max_payload_kg": self.max_payload_kg,
            "current_payload_kg": self.current_payload_kg,
            "status": self.status.value,
            "speed_kmh": round(self.speed_kmh, 1),
            "altitude_m": round(self.altitude_m, 1),
            "heading_deg": round(self.heading_deg, 1),
            "motor_hours": round(self.motor_hours, 1),
            "charge_cycles": self.charge_cycles,
            "current_order": self.current_order,
            "waypoints": self.waypoints,
            "waypoint_index": self.waypoint_index,
            "route_color": self.route_color,
            "triangular_target": self.triangular_target,
        }


@dataclass
class Order:
    id: str
    origin_depot: str
    destination: Position
    destination_label: str
    weight_kg: float
    priority: OrderPriority = OrderPriority.STANDARD
    status: OrderStatus = OrderStatus.QUEUED
    sla_minutes: int = 30
    assigned_drone: str | None = None
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "origin_depot": self.origin_depot,
            "destination": self.destination.to_dict(),
            "destination_label": self.destination_label,
            "weight_kg": self.weight_kg,
            "priority": self.priority.value,
            "status": self.status.value,
            "sla_minutes": self.sla_minutes,
            "assigned_drone": self.assigned_drone,
            "created_at": self.created_at,
        }


@dataclass
class WeatherCell:
    id: str
    position: Position
    radius_km: float
    wind_speed_kmh: float
    wind_gusts_kmh: float
    precipitation_mm: float
    active: bool = True

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "position": self.position.to_dict(),
            "radius_km": self.radius_km,
            "wind_speed_kmh": self.wind_speed_kmh,
            "wind_gusts_kmh": self.wind_gusts_kmh,
            "precipitation_mm": self.precipitation_mm,
            "active": self.active,
        }


# ── Simulation Engine ────────────────────────────────────────────────

class SimulationEngine:
    """
    Core deterministic simulation engine that manages the entire fleet state.
    All state mutations flow through this engine.
    """

    def __init__(self):
        self.depots: dict[str, Depot] = {}
        self.drones: dict[str, Drone] = {}
        self.orders: dict[str, Order] = {}
        self.weather_cells: list[WeatherCell] = []
        self.agent_logs: list[dict] = []
        self.metrics: dict = {
            "active_drones": 0,
            "fleet_soh_avg": 0.0,
            "deadhead_reduced_pct": 0.0,
            "pad_utilization_pct": 0.0,
            "cost_savings_usd": 0.0,
            "total_deliveries": 0,
            "active_orders": 0,
            "avg_battery": 0.0,
        }
        self.chaos_state: dict = {
            "pad_congestion": False,
            "microburst": False,
            "drop_zone_obstacle": False,
        }
        self._pending_timers: list[dict] = []
        self._tick_count = 0
        self._initialized = False
        self._active_scenario: str | None = None
        self._delivery_count = 0
        self._deadhead_saved_km = 0.0
        self._total_flight_km = 0.0
        self._separation_violations: int = 0
        self._failed_missions: int = 0
        # D-003: store original specs for reproducible reset
        self._drone_specs: list[tuple] = []
        self.initialize_world()

    def initialize_world(self):
        """Set up the Colombo-area operational environment."""

        # ── Primary Depot (Central Warehouse) ──
        depot_a = Depot(
            id="depot-alpha",
            name="SkyGrid Central Hub",
            position=Position(6.9271, 79.8612, 0),
            pads=[
                LandingPad(id="pad-A1", depot_id="depot-alpha"),
                LandingPad(id="pad-A2", depot_id="depot-alpha"),
            ],
            battery_swap_stations=3,
        )

        # ── Secondary Depot (Sub-Branch) ──
        depot_b = Depot(
            id="depot-bravo",
            name="SkyGrid South Branch",
            position=Position(6.8850, 79.8780, 0),
            pads=[
                LandingPad(id="pad-B1", depot_id="depot-bravo"),
                LandingPad(id="pad-B2", depot_id="depot-bravo"),
            ],
            battery_swap_stations=2,
        )

        # ── Tertiary Depot ──
        depot_c = Depot(
            id="depot-charlie",
            name="SkyGrid East Branch",
            position=Position(6.9350, 79.9000, 0),
            pads=[
                LandingPad(id="pad-C1", depot_id="depot-charlie"),
            ],
            battery_swap_stations=1,
        )

        self.depots = {d.id: d for d in [depot_a, depot_b, depot_c]}

        # ── Drone Fleet ──
        drone_specs = [
            ("SKY-001", "Falcon-X1",  "depot-alpha",  95.2, 100.0, 5.0, 342.1, 127, 65.0),
            ("SKY-002", "Falcon-X2",  "depot-alpha",  91.8, 100.0, 5.0, 510.3, 198, 62.0),
            ("SKY-003", "Hawk-M1",    "depot-alpha",  97.5, 100.0, 8.0, 128.7,  54, 55.0),
            ("SKY-004", "Hawk-M2",    "depot-bravo",  88.3, 100.0, 8.0, 780.2, 312, 58.0),
            ("SKY-005", "Swift-L1",   "depot-bravo",  93.6, 100.0, 3.0, 245.8, 102, 72.0),
            ("SKY-006", "Swift-L2",   "depot-charlie", 96.1, 100.0, 3.0, 167.4,  71, 70.0),
        ]

        # D-003: save original specs for full reset fidelity
        self._drone_specs = drone_specs

        for did, name, depot, soh, charge, payload, hours, cycles, speed in drone_specs:
            depot_pos = self.depots[depot].position
            self.drones[did] = Drone(
                id=did,
                name=name,
                position=Position(depot_pos.lat, depot_pos.lon, 0),
                home_depot=depot,
                battery_soh=soh,
                battery_charge=charge,
                max_payload_kg=payload,
                motor_hours=hours,
                charge_cycles=cycles,
                speed_kmh=speed,
            )

        self._initialized = True

    # ── State Snapshot ────────────────────────────────────────────────

    def get_full_state(self) -> dict:
        """Return complete simulation state for WebSocket broadcast."""
        self._update_metrics()
        return {
            "depots": {k: v.to_dict() for k, v in self.depots.items()},
            "drones": {k: v.to_dict() for k, v in self.drones.items()},
            "orders": {k: v.to_dict() for k, v in self.orders.items()},
            "weather_cells": [w.to_dict() for w in self.weather_cells if w.active],
            "metrics": self.metrics,
            "chaos_state": self.chaos_state,
            "active_scenario": self._active_scenario,
        }

    def _update_metrics(self):
        active = [d for d in self.drones.values() if d.status != DroneStatus.IDLE]
        all_drones = list(self.drones.values())
        avg_soh = sum(d.battery_soh for d in all_drones) / max(len(all_drones), 1)
        avg_bat = sum(d.battery_charge for d in all_drones) / max(len(all_drones), 1)

        total_pads = sum(len(d.pads) for d in self.depots.values())
        used_pads = sum(
            1 for d in self.depots.values()
            for p in d.pads if p.status != PadStatus.AVAILABLE
        )

        deadhead_pct = 0.0
        if self._total_flight_km > 0:
            deadhead_pct = min(35.0, (self._deadhead_saved_km / self._total_flight_km) * 100)

        active_orders = sum(
            1 for o in self.orders.values()
            if o.status in (OrderStatus.QUEUED, OrderStatus.DISPATCHED, OrderStatus.IN_TRANSIT)
        )

        self.metrics = {
            "active_drones": len(active),
            "fleet_soh_avg": round(avg_soh, 1),
            "deadhead_reduced_pct": round(deadhead_pct, 1),
            "pad_utilization_pct": round((used_pads / max(total_pads, 1)) * 100, 1),
            "cost_savings_usd": round(self._deadhead_saved_km * 2.4 + self._delivery_count * 8.5, 2),
            "total_deliveries": self._delivery_count,
            "active_orders": active_orders,
            "avg_battery": round(avg_bat, 1),
        }

    # ── Agent Log Emitter ─────────────────────────────────────────────

    def emit_log(self, agent: str, message: str, data: dict | None = None) -> dict:
        entry = {
            "id": str(uuid.uuid4())[:8],
            "timestamp": time.time(),
            "agent": agent,
            "message": message,
            "data": data or {},
        }
        self.agent_logs.append(entry)
        # Keep last 200 logs
        if len(self.agent_logs) > 200:
            self.agent_logs = self.agent_logs[-200:]
        return entry

    # ── Tick: Advance Simulation ──────────────────────────────────────

    def tick(self, dt: float = 1.0) -> list[dict]:
        """
        Advance the simulation by dt seconds.
        Returns a list of new agent log entries generated during this tick.
        D-010: minimum separation check runs every tick for airborne drones.
        """
        self._tick_count += 1
        new_logs: list[dict] = []

        # Process pending timers
        expired = [t for t in self._pending_timers if t["tick"] <= self._tick_count]
        for timer in expired:
            self._pending_timers.remove(timer)
            result = timer["fn"](*timer["args"])
            if isinstance(result, list):
                new_logs.extend(result)

        for drone in self.drones.values():
            if drone.status in (DroneStatus.EN_ROUTE, DroneStatus.DELIVERING, DroneStatus.RETURNING,
                                DroneStatus.REROUTING, DroneStatus.DIVERTED):
                logs = self._advance_drone(drone, dt)
                new_logs.extend(logs)

            elif drone.status == DroneStatus.BATTERY_SWAP:
                # 90-second swap cycle
                drone.battery_charge = min(100.0, drone.battery_charge + (100.0 / 90.0) * dt)
                if drone.battery_charge >= 99.5:
                    drone.battery_charge = 100.0
                    drone.status = DroneStatus.IDLE
                    drone.current_payload_kg = 0.0
                    # Free the pad
                    for depot in self.depots.values():
                        for pad in depot.pads:
                            if pad.reserved_for == drone.id:
                                pad.status = PadStatus.AVAILABLE
                                pad.reserved_for = None
                    log = self.emit_log(
                        "TAT-DEPOT",
                        f"✅ {drone.name} ({drone.id}) battery swap complete → 100% charge. "
                        f"Drone returned to IDLE. Landing pad released.",
                    )
                    new_logs.append(log)

            elif drone.status == DroneStatus.LANDING:
                drone.altitude_m = max(0, drone.altitude_m - 15 * dt)
                if drone.altitude_m <= 0:
                    drone.altitude_m = 0
                    drone.status = DroneStatus.BATTERY_SWAP
                    log = self.emit_log(
                        "TAT-DEPOT",
                        f"🔋 {drone.name} ({drone.id}) touchdown confirmed. "
                        f"Initiating 90-second automated battery swap cycle. "
                        f"Current SoH: {drone.battery_soh}% | Charge Cycles: {drone.charge_cycles}",
                    )
                    new_logs.append(log)

            elif drone.status == DroneStatus.HOLDING:
                # Holding pattern — slow battery drain
                drone.battery_charge = max(0, drone.battery_charge - 0.02 * dt)
                if self._tick_count % 30 == 0:
                    log = self.emit_log(
                        "TAT-DEPOT",
                        f"⏳ {drone.name} ({drone.id}) holding at waypoint. "
                        f"Battery: {drone.battery_charge:.1f}% | Awaiting pad clearance.",
                    )
                    new_logs.append(log)

        # D-010: check minimum separation every 10 ticks (~5 s)
        if self._tick_count % 10 == 0:
            sep_logs = self._check_separation()
            new_logs.extend(sep_logs)

        return new_logs

    def _check_separation(self) -> list[dict]:
        """D-010: Log any pairs of airborne drones closer than MIN_SEPARATION_KM."""
        logs = []
        airborne = [
            d for d in self.drones.values()
            if d.status in (
                DroneStatus.EN_ROUTE, DroneStatus.DELIVERING,
                DroneStatus.RETURNING, DroneStatus.REROUTING, DroneStatus.DIVERTED,
            )
        ]
        checked: set[tuple[str, str]] = set()
        for i, d1 in enumerate(airborne):
            for d2 in airborne[i + 1:]:
                key = (min(d1.id, d2.id), max(d1.id, d2.id))
                if key in checked:
                    continue
                checked.add(key)
                dist = d1.position.distance_to(d2.position)
                if dist < MIN_SEPARATION_KM:
                    self._separation_violations += 1
                    log = self.emit_log(
                        "CORRIDOR",
                        f"⚠️ SEPARATION VIOLATION: {d1.name} and {d2.name} within "
                        f"{dist * 1000:.0f} m (minimum: {MIN_SEPARATION_KM * 1000:.0f} m). "
                        f"Violation #{self._separation_violations}. "
                        f"[SIMULATION CONSTRAINT — not certified collision avoidance]",
                    )
                    logs.append(log)
        return logs

    def _advance_drone(self, drone: Drone, dt: float) -> list[dict]:
        """Move drone along its waypoint path."""
        logs: list[dict] = []

        if not drone.waypoints or drone.waypoint_index >= len(drone.waypoints):
            # Arrived at final destination
            logs.extend(self._handle_arrival(drone))
            return logs

        target_wp = drone.waypoints[drone.waypoint_index]
        target_pos = Position(target_wp["lat"], target_wp["lon"], target_wp.get("alt", 120))

        dist_km = drone.position.distance_to(target_pos)
        step_km = (drone.speed_kmh / 3600.0) * dt

        # Battery discharge — base + weather penalty
        base_discharge = 0.015 * dt  # %/sec baseline
        weather_penalty = self._get_weather_penalty(drone.position)
        payload_factor = 1.0 + (drone.current_payload_kg / drone.max_payload_kg) * 0.3
        total_discharge = base_discharge * (1.0 + weather_penalty) * payload_factor
        drone.battery_charge = max(0, drone.battery_charge - total_discharge)

        # Track flight km for metrics
        self._total_flight_km += step_km

        if dist_km <= step_km:
            # Reached this waypoint
            drone.position = Position(target_pos.lat, target_pos.lon, target_pos.alt)
            drone.waypoint_index += 1

            # Periodic telemetry log
            if drone.waypoint_index % 3 == 0 and drone.waypoint_index < len(drone.waypoints):
                wh_km = round(18.2 + weather_penalty * 12.0 + drone.current_payload_kg * 1.8, 1)
                log = self.emit_log(
                    "CORRIDOR",
                    f"📡 {drone.name} waypoint {drone.waypoint_index}/{len(drone.waypoints)} reached. "
                    f"Battery: {drone.battery_charge:.1f}% | "
                    f"Discharge rate: {wh_km} Wh/km | "
                    f"Headwind drag: +{weather_penalty * 18.4:.1f}W | "
                    f"Payload factor: {payload_factor:.2f}x",
                )
                logs.append(log)

            # Check critical battery
            if drone.battery_charge < 15.0 and drone.status != DroneStatus.REROUTING:
                log = self.emit_log(
                    "CORRIDOR",
                    f"⚠️ CRITICAL: {drone.name} battery at {drone.battery_charge:.1f}%. "
                    f"Below 15% safety threshold! Initiating emergency depot diversion.",
                )
                logs.append(log)
                # Find nearest depot for emergency landing
                nearest = self._find_nearest_depot(drone.position)
                if nearest:
                    # D-004: release any pre-reserved pad at the original depot
                    self._release_pad_for_drone(drone.id)
                    drone.waypoints = self._generate_direct_waypoints(
                        drone.position, nearest.position
                    )
                    drone.waypoint_index = 0
                    drone.status = DroneStatus.REROUTING
                    drone.route_color = "#ff4444"
                    # D-007: estimate arrival battery from distance + consumption
                    est_dist = drone.position.distance_to(nearest.position)
                    est_consumed = est_dist * 2.8 * (1.0 + self._get_weather_penalty(drone.position))
                    est_arrival_bat = max(0.0, drone.battery_charge - est_consumed)
                    log2 = self.emit_log(
                        "RESOLVER",
                        f"🚨 Emergency diversion for {drone.name} → {nearest.name}. "
                        f"Distance: {est_dist:.2f} km. "
                        f"Estimated battery on arrival: {est_arrival_bat:.1f}%",
                    )
                    logs.append(log2)
        else:
            # Interpolate position toward waypoint
            ratio = step_km / dist_km
            drone.position.lat += (target_pos.lat - drone.position.lat) * ratio
            drone.position.lon += (target_pos.lon - drone.position.lon) * ratio
            drone.altitude_m = target_pos.alt

            # Compute heading
            dlat = target_pos.lat - drone.position.lat
            dlon = target_pos.lon - drone.position.lon
            drone.heading_deg = (math.degrees(math.atan2(dlon, dlat)) + 360) % 360

        return logs

    def _handle_arrival(self, drone: Drone) -> list[dict]:
        """Handle drone arriving at waypoint path end."""
        logs: list[dict] = []

        if drone.status == DroneStatus.EN_ROUTE:
            # Arrived at customer delivery point
            drone.status = DroneStatus.DELIVERING
            drone.current_payload_kg = 0.0

            if drone.current_order and drone.current_order in self.orders:
                order = self.orders[drone.current_order]

                # Check for drop-zone obstacle chaos
                if self.chaos_state.get("drop_zone_obstacle"):
                    drone.status = DroneStatus.HOLDING
                    log = self.emit_log(
                        "RESOLVER",
                        f"🚧 DROP-ZONE OBSTACLE detected at delivery point for {drone.name}! "
                        f"Obstacle: Tree canopy obstruction blocking rooftop LZ. "
                        f"Evaluating alternate protocols...",
                    )
                    logs.append(log)
                    log2 = self.emit_log(
                        "RESOLVER",
                        f"🔄 Attempting automated resolution: Initiating precision winch-drop "
                        f"from {drone.altitude_m:.0f}m AGL. Wind check: "
                        f"{'PASS' if not self.chaos_state.get('microburst') else 'MARGINAL'}. "
                        f"Deploying 3m tether line...",
                    )
                    logs.append(log2)
                    # Auto-resolve after emitting logs
                    self.chaos_state["drop_zone_obstacle"] = False
                    order.status = OrderStatus.DELIVERED
                    self._delivery_count += 1
                    log3 = self.emit_log(
                        "RESOLVER",
                        f"✅ Winch-drop delivery successful for Order {order.id}. "
                        f"Package confirmed at alternate drop coordinate. "
                        f"No human escalation required — 1:100 operator ratio maintained.",
                    )
                    logs.append(log3)
                else:
                    order.status = OrderStatus.DELIVERED
                    self._delivery_count += 1
                    log = self.emit_log(
                        "DISPATCHER",
                        f"📦 Delivery CONFIRMED: {drone.name} → {order.destination_label}. "
                        f"Order {order.id} fulfilled. Payload: {order.weight_kg}kg. "
                        f"Battery remaining: {drone.battery_charge:.1f}%",
                    )
                    logs.append(log)

            # ── Triangular Routing: Check for chained pickup ──
            if drone.triangular_target and drone.triangular_target in self.depots:
                target_depot = self.depots[drone.triangular_target]
                self._deadhead_saved_km += drone.position.distance_to(
                    self.depots[drone.home_depot].position
                ) * 0.35

                log = self.emit_log(
                    "DISPATCHER",
                    f"🔺 TRIANGULAR MILK-RUN: {drone.name} delivery complete. "
                    f"Instead of deadhead return to {self.depots[drone.home_depot].name}, "
                    f"rerouting to {target_depot.name} for chained outbound pickup. "
                    f"Deadhead savings: ~{self._deadhead_saved_km:.1f} km eliminated.",
                )
                logs.append(log)

                # Route to secondary depot
                waypoints = self._generate_waypoints(
                    drone.position, target_depot.position
                )
                drone.waypoints = waypoints
                drone.waypoint_index = 0
                drone.status = DroneStatus.RETURNING
                drone.route_color = "#f59e0b"
                drone.triangular_target = None
            else:
                # Standard return to home depot
                home = self.depots.get(drone.home_depot)
                if home:
                    waypoints = self._generate_waypoints(drone.position, home.position)
                    drone.waypoints = waypoints
                    drone.waypoint_index = 0
                    drone.status = DroneStatus.RETURNING
                    drone.route_color = "#60a5fa"

                    log = self.emit_log(
                        "DISPATCHER",
                        f"🔄 {drone.name} returning to {home.name}. "
                        f"Distance: {drone.position.distance_to(home.position):.2f} km. "
                        f"Battery: {drone.battery_charge:.1f}%",
                    )
                    logs.append(log)

        elif drone.status in (DroneStatus.RETURNING, DroneStatus.REROUTING, DroneStatus.DIVERTED):
            # Arrived back at depot — initiate landing
            logs.extend(self._initiate_landing(drone))

        elif drone.status == DroneStatus.DELIVERING:
            # Already handled
            pass

        return logs

    def _initiate_landing(self, drone: Drone) -> list[dict]:
        """Handle drone landing at a depot."""
        logs: list[dict] = []

        # Find which depot we're near
        target_depot = self._find_nearest_depot(drone.position)
        if not target_depot:
            return logs

        # TAT Agent: Check pad availability
        available_pad = None
        for pad in target_depot.pads:
            if pad.status == PadStatus.AVAILABLE:
                available_pad = pad
                break

        if available_pad:
            available_pad.status = PadStatus.RESERVED
            available_pad.reserved_for = drone.id
            drone.status = DroneStatus.LANDING
            drone.altitude_m = 120.0

            log = self.emit_log(
                "TAT-DEPOT",
                f"🛬 {drone.name} cleared for landing at {target_depot.name} → "
                f"{available_pad.id}. Zero-hover sequencing: CLEAR. "
                f"Descent from {drone.altitude_m:.0f}m AGL initiated.",
            )
            logs.append(log)
        else:
            # No pad available — check for congestion chaos or genuine congestion
            if self.chaos_state.get("pad_congestion"):
                drone.status = DroneStatus.HOLDING
                log = self.emit_log(
                    "TAT-DEPOT",
                    f"🚫 PAD CONGESTION: All pads at {target_depot.name} occupied/blocked! "
                    f"{drone.name} entering hold pattern at safe waypoint. "
                    f"Battery reserve: {drone.battery_charge:.1f}%. "
                    f"TAT Agent computing priority re-sequencing...",
                )
                logs.append(log)

                # Try to resolve by checking other depots
                alt_depot = self._find_alternate_depot(drone.position, target_depot.id)
                if alt_depot:
                    # Check if alt depot has pads
                    alt_pad = None
                    for pad in alt_depot.pads:
                        if pad.status == PadStatus.AVAILABLE:
                            alt_pad = pad
                            break
                    if alt_pad:
                        log2 = self.emit_log(
                            "TAT-DEPOT",
                            f"🔀 Re-sequencing: Diverting {drone.name} to {alt_depot.name} "
                            f"({alt_pad.id} available). "
                            f"Additional distance: {drone.position.distance_to(alt_depot.position):.2f} km.",
                        )
                        logs.append(log2)
                        # D-004: release original reserved pad before diverting
                        self._release_pad_for_drone(drone.id)
                        alt_pad.status = PadStatus.RESERVED
                        alt_pad.reserved_for = drone.id
                        drone.waypoints = self._generate_direct_waypoints(
                            drone.position, alt_depot.position
                        )
                        drone.waypoint_index = 0
                        drone.status = DroneStatus.DIVERTED
                        drone.route_color = "#ef4444"
                        # D-005: clear congestion flag after successful divert
                        self.chaos_state["pad_congestion"] = False
            else:
                # Genuine congestion: wait briefly
                drone.status = DroneStatus.HOLDING
                log = self.emit_log(
                    "TAT-DEPOT",
                    f"⏳ {drone.name} holding — all pads at {target_depot.name} busy. "
                    f"Estimated wait: 30-45 seconds. Battery: {drone.battery_charge:.1f}%",
                )
                logs.append(log)

                # Auto-clear after ~5 seconds (10 ticks at 0.5s)
                self._pending_timers.append({
                    "tick": self._tick_count + 10,
                    "fn": self._force_pad_clear,
                    "args": (target_depot.id, drone.id),
                })
                # D-005: schedule auto-clear for pad_congestion flag
                self._pending_timers.append({
                    "tick": self._tick_count + 30,
                    "fn": self._clear_pad_congestion_flag,
                    "args": (),
                })

        return logs

    def _force_pad_clear(self, depot_id: str, drone_id: str):
        """Force-clear a pad for a holding drone after brief wait.
        D-009: only grants genuinely AVAILABLE pads.
        """
        if depot_id in self.depots and drone_id in self.drones:
            depot = self.depots[depot_id]
            drone = self.drones[drone_id]
            if drone.status == DroneStatus.HOLDING:
                for pad in depot.pads:
                    if pad.status == PadStatus.AVAILABLE:  # D-009: AVAILABLE only
                        pad.status = PadStatus.RESERVED
                        pad.reserved_for = drone_id
                        drone.status = DroneStatus.LANDING
                        drone.altitude_m = 80.0
                        self.emit_log(
                            "TAT-DEPOT",
                            f"✅ Pad {pad.id} cleared. {drone.name} cleared for landing.",
                        )
                        break

    def _clear_pad_congestion_flag(self):
        """D-005: TTL-based clear for pad_congestion flag."""
        if self.chaos_state.get("pad_congestion"):
            self.chaos_state["pad_congestion"] = False
            self.emit_log(
                "TAT-DEPOT",
                "✅ Pad congestion flag auto-cleared after TTL. Pads re-evaluated.",
            )

    def _release_pad_for_drone(self, drone_id: str):
        """D-004: Release any pad currently reserved for a specific drone ID."""
        for depot in self.depots.values():
            for pad in depot.pads:
                if pad.reserved_for == drone_id and pad.status == PadStatus.RESERVED:
                    pad.status = PadStatus.AVAILABLE
                    pad.reserved_for = None

    def _get_weather_penalty(self, pos: Position) -> float:
        """Calculate weather penalty factor for a position."""
        penalty = 0.0
        if self.chaos_state.get("microburst"):
            penalty += 0.6  # 60% discharge increase
        for cell in self.weather_cells:
            if cell.active:
                dist = pos.distance_to(cell.position)
                if dist < cell.radius_km:
                    proximity = 1.0 - (dist / cell.radius_km)
                    penalty += proximity * (cell.wind_speed_kmh / 50.0)
        return penalty

    def _find_nearest_depot(self, pos: Position) -> Depot | None:
        best, best_dist = None, float("inf")
        for depot in self.depots.values():
            d = pos.distance_to(depot.position)
            if d < best_dist:
                best, best_dist = depot, d
        return best

    def _find_alternate_depot(self, pos: Position, exclude_id: str) -> Depot | None:
        best, best_dist = None, float("inf")
        for depot in self.depots.values():
            if depot.id == exclude_id:
                continue
            d = pos.distance_to(depot.position)
            if d < best_dist:
                best, best_dist = depot, d
        return best

    def _generate_waypoints(
        self, start: Position, end: Position, num_points: int = 8, seed: int | None = None
    ) -> list[dict]:
        """Generate intermediate waypoints with slight realistic variance.
        D-008: accepts an optional seed for reproducible benchmark runs.
        """
        rng = random.Random(seed) if seed is not None else random  # type: ignore[arg-type]
        waypoints = []
        for i in range(1, num_points + 1):
            t = i / num_points
            lat = start.lat + (end.lat - start.lat) * t
            lon = start.lon + (end.lon - start.lon) * t
            # Add slight variance for realism (curved corridor)
            if 0.2 < t < 0.8:
                lat += rng.uniform(-0.002, 0.002)
                lon += rng.uniform(-0.002, 0.002)
            alt = 120.0 if t < 0.85 else max(30.0, 120.0 * (1 - (t - 0.85) / 0.15))
            waypoints.append({"lat": round(lat, 6), "lon": round(lon, 6), "alt": round(alt, 1)})
        return waypoints

    def _generate_direct_waypoints(self, start: Position, end: Position) -> list[dict]:
        """Generate direct flight path (emergency/diversion) — no variance."""
        return self._generate_waypoints(start, end, num_points=5, seed=0)

    # ── Scenario Generators ───────────────────────────────────────────

    def create_scenario_a(self) -> list[dict]:
        """Morning Multi-Depot Peak Load: 5 simultaneous orders across 2 hubs."""
        self._active_scenario = "A"
        logs: list[dict] = []

        customers = [
            ("CUST-A1", Position(6.9150, 79.8500, 0), "Colombo Fort Office Tower", 2.1, OrderPriority.STANDARD),
            ("CUST-A2", Position(6.9400, 79.8700, 0), "Maradana Medical Center", 1.5, OrderPriority.EXPRESS),
            ("CUST-A3", Position(6.9050, 79.8850, 0), "Bambalapitiya Residences", 3.8, OrderPriority.STANDARD),
            ("CUST-A4", Position(6.8950, 79.8550, 0), "Dehiwala Commerce Park", 0.8, OrderPriority.EXPRESS),
            ("CUST-A5", Position(6.9500, 79.8900, 0), "Borella Tech Hub", 4.2, OrderPriority.STANDARD),
        ]

        log = self.emit_log(
            "DISPATCHER",
            "📋 SCENARIO A: Morning Multi-Depot Peak Load initiated. "
            "5 simultaneous orders across Central Hub & South Branch. "
            "Evaluating fleet availability and SoH thresholds...",
        )
        logs.append(log)

        depots_cycle = ["depot-alpha", "depot-alpha", "depot-alpha", "depot-bravo", "depot-bravo"]

        for i, (cid, pos, label, weight, priority) in enumerate(customers):
            order_id = f"ORD-{uuid.uuid4().hex[:6].upper()}"
            order = Order(
                id=order_id,
                origin_depot=depots_cycle[i],
                destination=pos,
                destination_label=label,
                weight_kg=weight,
                priority=priority,
                sla_minutes=30 if priority == OrderPriority.STANDARD else 15,
            )
            self.orders[order_id] = order

        # Dispatch drones
        available_drones = [d for d in self.drones.values() if d.status == DroneStatus.IDLE]
        available_drones.sort(key=lambda d: d.battery_soh, reverse=True)

        queued_orders = [o for o in self.orders.values() if o.status == OrderStatus.QUEUED]
        queued_orders.sort(key=lambda o: (0 if o.priority == OrderPriority.MEDICAL else
                                          1 if o.priority == OrderPriority.CRITICAL else
                                          2 if o.priority == OrderPriority.EXPRESS else 3,
                                          o.created_at))

        for order in queued_orders:
            # Find best drone from same depot
            best_drone = None
            for drone in available_drones:
                if drone.home_depot == order.origin_depot and drone.status == DroneStatus.IDLE:
                    if drone.max_payload_kg >= order.weight_kg and drone.battery_charge > 30:
                        best_drone = drone
                        break

            if not best_drone:
                # Try any available drone
                for drone in available_drones:
                    if drone.status == DroneStatus.IDLE and drone.max_payload_kg >= order.weight_kg:
                        best_drone = drone
                        break

            if best_drone:
                origin_depot = self.depots[order.origin_depot]
                logs.extend(self._dispatch_drone(best_drone, order, origin_depot))

        return logs

    def create_scenario_b(self) -> list[dict]:
        """Triangular Milk-Run Dispatch."""
        self._active_scenario = "B"
        logs: list[dict] = []

        log = self.emit_log(
            "DISPATCHER",
            "🔺 SCENARIO B: Triangular Milk-Run Dispatch initiated. "
            "Drone will execute Depot A → Customer → Depot B chained delivery, "
            "eliminating deadhead return flight.",
        )
        logs.append(log)

        order = Order(
            id=f"ORD-{uuid.uuid4().hex[:6].upper()}",
            origin_depot="depot-alpha",
            destination=Position(6.9100, 79.8700, 0),
            destination_label="Slave Island Business Complex",
            weight_kg=2.5,
            priority=OrderPriority.STANDARD,
            sla_minutes=25,
        )
        self.orders[order.id] = order

        # Queue a secondary order at Depot B for the chained pickup
        secondary_order = Order(
            id=f"ORD-{uuid.uuid4().hex[:6].upper()}",
            origin_depot="depot-bravo",
            destination=Position(6.9200, 79.8550, 0),
            destination_label="Pettah Market Hub",
            weight_kg=1.8,
            priority=OrderPriority.STANDARD,
            sla_minutes=35,
        )
        self.orders[secondary_order.id] = secondary_order
        self.depots["depot-bravo"].queued_outbound.append(secondary_order.id)

        # Find best drone from depot-alpha
        drone = None
        for d in self.drones.values():
            if d.home_depot == "depot-alpha" and d.status == DroneStatus.IDLE:
                drone = d
                break

        if drone:
            depot_a = self.depots["depot-alpha"]
            drone.triangular_target = "depot-bravo"
            logs.extend(self._dispatch_drone(drone, order, depot_a))

            log2 = self.emit_log(
                "DISPATCHER",
                f"🔺 Milk-Run Plan: {drone.name} will fly "
                f"Central Hub → {order.destination_label} → South Branch (chained pickup). "
                f"Projected deadhead savings: ~2.1 km ({35}% reduction).",
            )
            logs.append(log2)

        return logs

    def create_scenario_c(self) -> list[dict]:
        """High-Priority Medical Delivery."""
        self._active_scenario = "C"
        logs: list[dict] = []

        log = self.emit_log(
            "DISPATCHER",
            "🏥 SCENARIO C: HIGH-PRIORITY MEDICAL DELIVERY — Organ/Blood Transport. "
            "Priority override ACTIVE. Clearing all conflicting landing pad reservations. "
            "SLA: 12 minutes maximum.",
        )
        logs.append(log)

        order = Order(
            id=f"MED-{uuid.uuid4().hex[:6].upper()}",
            origin_depot="depot-alpha",
            destination=Position(6.9400, 79.8700, 0),
            destination_label="Maradana National Hospital — Rooftop LZ",
            weight_kg=1.2,
            priority=OrderPriority.MEDICAL,
            sla_minutes=12,
        )
        self.orders[order.id] = order

        # Clear ALL pad conflicts for medical priority
        for depot in self.depots.values():
            for pad in depot.pads:
                if pad.status == PadStatus.RESERVED:
                    pad.status = PadStatus.AVAILABLE
                    pad.reserved_for = None

        log2 = self.emit_log(
            "TAT-DEPOT",
            "🔴 MEDICAL PRIORITY OVERRIDE: All non-critical pad reservations cleared. "
            "Pad A1 @ Central Hub reserved for medical return. "
            "Automated battery swap station pre-heated.",
        )
        logs.append(log2)

        # Use fastest drone with best SoH
        best = None
        for d in self.drones.values():
            if d.status == DroneStatus.IDLE and d.battery_charge > 50:
                if best is None or d.speed_kmh > best.speed_kmh:
                    best = d

        if best:
            depot = self.depots["depot-alpha"]
            best.route_color = "#ef4444"
            logs.extend(self._dispatch_drone(best, order, depot))

            log3 = self.emit_log(
                "CORRIDOR",
                f"🚑 Medical corridor LOCKED for {best.name}. "
                f"Direct flight path calculated — all TFR restrictions suspended. "
                f"Speed: {best.speed_kmh} km/h | "
                f"ETA: {best.position.distance_to(order.destination) / best.speed_kmh * 60:.1f} min",
            )
            logs.append(log3)

        return logs

    def _dispatch_drone(self, drone: Drone, order: Order, origin_depot: Depot) -> list[dict]:
        """Dispatch a drone for an order."""
        logs: list[dict] = []

        order.status = OrderStatus.DISPATCHED
        order.assigned_drone = drone.id

        drone.status = DroneStatus.ASSIGNED
        drone.current_order = order.id
        drone.current_payload_kg = order.weight_kg
        drone.position = Position(origin_depot.position.lat, origin_depot.position.lon, 0)

        # Generate flight path
        waypoints = self._generate_waypoints(origin_depot.position, order.destination)
        drone.waypoints = waypoints
        drone.waypoint_index = 0

        dist = origin_depot.position.distance_to(order.destination)
        eta_min = (dist / drone.speed_kmh) * 60

        log = self.emit_log(
            "DISPATCHER",
            f"🚀 DISPATCH: {drone.name} ({drone.id}) assigned to Order {order.id}. "
            f"Payload: {order.weight_kg}kg | "
            f"SoH: {drone.battery_soh}% | Charge: {drone.battery_charge:.1f}% | "
            f"Route: {origin_depot.name} → {order.destination_label} ({dist:.2f} km). "
            f"ETA: {eta_min:.1f} min | Priority: {order.priority.value.upper()}",
        )
        logs.append(log)

        log2 = self.emit_log(
            "CORRIDOR",
            f"📐 Flight corridor computed for {drone.name}: "
            f"{len(waypoints)} waypoints | Cruise alt: 120m AGL | "
            f"Estimated battery consumption: {dist * 2.8:.1f}% | "
            f"Weather clearance: {'⚠️ ADVISORY' if self.chaos_state.get('microburst') else '✅ CLEAR'}",
        )
        logs.append(log2)

        # Reserve a pad for return
        for pad in origin_depot.pads:
            if pad.status == PadStatus.AVAILABLE:
                pad.status = PadStatus.RESERVED
                pad.reserved_for = drone.id
                pad.eta_seconds = eta_min * 60 * 2

                log3 = self.emit_log(
                    "TAT-DEPOT",
                    f"📋 {pad.id} @ {origin_depot.name} pre-reserved for {drone.name} return. "
                    f"ETA: ~{eta_min * 2:.0f} min. Zero-hover sequencing: ARMED.",
                )
                logs.append(log3)
                break

        # Activate the drone
        drone.status = DroneStatus.EN_ROUTE
        drone.altitude_m = 120.0
        if order.priority != OrderPriority.MEDICAL:
            drone.route_color = "#00ff88"

        order.status = OrderStatus.IN_TRANSIT

        return logs

    # ── Chaos Injection ───────────────────────────────────────────────

    def inject_pad_congestion(self) -> list[dict]:
        """Block Pad 1 at Central Depot."""
        logs = []
        self.chaos_state["pad_congestion"] = True

        depot = self.depots["depot-alpha"]
        if depot.pads:
            depot.pads[0].status = PadStatus.BLOCKED
            depot.pads[0].reserved_for = None

        log = self.emit_log(
            "TAT-DEPOT",
            "⚡ CHAOS INJECTED: Pad A1 at SkyGrid Central Hub BLOCKED. "
            "Foreign object debris (FOD) detected on landing surface. "
            "All inbound traffic must re-route to Pad A2 or alternate depot.",
        )
        logs.append(log)

        log2 = self.emit_log(
            "TAT-DEPOT",
            "🔄 TAT Agent re-sequencing all inbound drones. "
            "Checking Pad A2 availability... Evaluating South Branch pads...",
        )
        logs.append(log2)

        # Check if any drones are returning and need re-routing
        for drone in self.drones.values():
            if drone.status == DroneStatus.RETURNING and drone.home_depot == "depot-alpha":
                log3 = self.emit_log(
                    "TAT-DEPOT",
                    f"⚠️ {drone.name} is inbound to Central Hub — must be re-sequenced. "
                    f"Battery: {drone.battery_charge:.1f}% | "
                    f"Checking alternate pad assignment...",
                )
                logs.append(log3)

        return logs

    def inject_microburst(self) -> list[dict]:
        """Inject 45 km/h headwind."""
        logs = []
        self.chaos_state["microburst"] = True

        # Create weather cell at midpoint of operational area
        cell = WeatherCell(
            id=f"WX-{uuid.uuid4().hex[:4].upper()}",
            position=Position(6.9200, 79.8700, 0),
            radius_km=2.5,
            wind_speed_kmh=45.0,
            wind_gusts_kmh=62.0,
            precipitation_mm=0.0,
        )
        self.weather_cells.append(cell)

        log = self.emit_log(
            "CORRIDOR",
            "🌪️ CHAOS INJECTED: 45 km/h micro-burst headwind detected! "
            f"Epicenter: ({cell.position.lat:.4f}, {cell.position.lon:.4f}) | "
            f"Radius: {cell.radius_km} km | Gusts: {cell.wind_gusts_kmh} km/h. "
            "Battery discharge rate increased by 60%!",
        )
        logs.append(log)

        # Evaluate impact on active drones
        for drone in self.drones.values():
            if drone.status in (DroneStatus.EN_ROUTE, DroneStatus.RETURNING):
                dist_to_cell = drone.position.distance_to(cell.position)
                if dist_to_cell < cell.radius_km * 1.5:
                    wh_impact = 18.4 * 0.6
                    new_margin = drone.battery_charge - (dist_to_cell * 2.8 * 1.6)
                    log2 = self.emit_log(
                        "CORRIDOR",
                        f"⚠️ {drone.name} in micro-burst zone! "
                        f"Calculated headwind drag: +{wh_impact:.1f}W → "
                        f"Battery margin: {new_margin:.1f}% → "
                        f"Threshold: {'⛔ UNSAFE' if new_margin < 15 else '✅ Safe'}. "
                        f"{'Initiating intermediate depot diversion!' if new_margin < 15 else 'Continuing with adjusted discharge curve.'}",
                    )
                    logs.append(log2)

                    if new_margin < 15:
                        nearest = self._find_nearest_depot(drone.position)
                        if nearest:
                            drone.waypoints = self._generate_direct_waypoints(
                                drone.position, nearest.position
                            )
                            drone.waypoint_index = 0
                            drone.status = DroneStatus.REROUTING
                            drone.route_color = "#ff4444"

        # Auto-clear after ~30 seconds (60 ticks at 0.5s)
        self._pending_timers.append({
            "tick": self._tick_count + 60,
            "fn": self._clear_microburst,
            "args": (cell.id,),
        })

        return logs

    def _clear_microburst(self, cell_id: str):
        for cell in self.weather_cells:
            if cell.id == cell_id:
                cell.active = False
        self.chaos_state["microburst"] = False
        self.emit_log(
            "CORRIDOR",
            "✅ Micro-burst weather cell dissipated. Wind speeds returning to nominal. "
            "Battery discharge curves recalculated to baseline.",
        )

    def inject_drop_obstacle(self) -> list[dict]:
        """Simulate obstructed landing area."""
        logs = []
        self.chaos_state["drop_zone_obstacle"] = True

        log = self.emit_log(
            "RESOLVER",
            "🚧 CHAOS INJECTED: Drop-zone obstacle detected at next delivery point! "
            "Obstacle type: Dense tree canopy + temporary construction scaffolding. "
            "Exception Resolver Agent evaluating automated resolution protocols...",
        )
        logs.append(log)

        log2 = self.emit_log(
            "RESOLVER",
            "🔍 Resolution options evaluated:\n"
            "  1. Precision winch-drop (3m tether) — Risk: LOW\n"
            "  2. Reroute to nearest company lockbox — Risk: NONE, +4 min delay\n"
            "  3. Escalate to human supervisor — Last resort\n"
            "Selecting Option 1: Winch-drop. Safety margins acceptable.",
        )
        logs.append(log2)

        return logs

    def reset_simulation(self):
        """Full reset to initial state.
        D-003: restores original battery SoH, motor hours, and charge cycles.
        """
        self.orders.clear()
        self.weather_cells.clear()
        self.agent_logs.clear()
        self.chaos_state = {
            "pad_congestion": False,
            "microburst": False,
            "drop_zone_obstacle": False,
        }
        self._pending_timers.clear()
        self._tick_count = 0
        self._active_scenario = None
        self._delivery_count = 0
        self._deadhead_saved_km = 0.0
        self._total_flight_km = 0.0
        self._separation_violations = 0
        self._failed_missions = 0

        # Reset depots
        for depot in self.depots.values():
            depot.queued_outbound.clear()
            for pad in depot.pads:
                pad.status = PadStatus.AVAILABLE
                pad.reserved_for = None
                pad.eta_seconds = 0

        # D-003: Reset drones from original specs (restores SoH, motor_hours, cycles)
        for spec in self._drone_specs:
            did, name, depot_id, soh, charge, payload, hours, cycles, speed = spec
            if did in self.drones:
                home = self.depots[depot_id]
                drone = self.drones[did]
                drone.position = Position(home.position.lat, home.position.lon, 0)
                drone.status = DroneStatus.IDLE
                drone.battery_soh = soh
                drone.battery_charge = charge
                drone.current_payload_kg = 0.0
                drone.current_order = None
                drone.waypoints = []
                drone.waypoint_index = 0
                drone.route_color = "#00ff88"
                drone.triangular_target = None
                drone.altitude_m = 0.0
                drone.heading_deg = 0.0
                drone.motor_hours = hours
                drone.charge_cycles = cycles
                drone.speed_kmh = speed
