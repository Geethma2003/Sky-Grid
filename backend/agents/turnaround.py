"""
Turnaround (TAT) & Depot Agent
================================
Pad Queue & Battery Swap Orchestrator.
Controls landing pads and battery-swap stations at enterprise depots.
"""

from services.simulation_engine import (
    SimulationEngine, Drone, DroneStatus, PadStatus, Depot
)


class TurnaroundAgent:
    """
    TAT & Depot Agent — manages zero-hover sequencing, pad priority,
    battery swap cycles, and depot infrastructure.
    """

    AGENT_NAME = "TAT-DEPOT"
    SWAP_CYCLE_SECONDS = 90

    def __init__(self, engine: SimulationEngine):
        self.engine = engine

    def get_depot_status(self) -> list[dict]:
        """Get comprehensive depot status report."""
        logs = []

        for depot in self.engine.depots.values():
            pad_summary = ", ".join(
                f"{p.id}: {p.status.value}" + (f" (→{p.reserved_for})" if p.reserved_for else "")
                for p in depot.pads
            )

            inbound = sum(
                1 for d in self.engine.drones.values()
                if d.status in (DroneStatus.RETURNING, DroneStatus.LANDING, DroneStatus.DIVERTED)
                and self.engine._find_nearest_depot(d.position) and
                self.engine._find_nearest_depot(d.position).id == depot.id
            )

            log = self.engine.emit_log(
                self.AGENT_NAME,
                f"🏭 {depot.name} status: "
                f"Pads: [{pad_summary}] | "
                f"Swap stations: {depot.battery_swap_stations} | "
                f"Inbound: {inbound} drone(s) | "
                f"Queued outbound: {len(depot.queued_outbound)} order(s)",
            )
            logs.append(log)

        return logs

    def check_pad_conflicts(self) -> list[dict]:
        """
        Zero-hover sequencing: detect and resolve potential simultaneous arrivals.
        """
        logs = []

        for depot in self.engine.depots.values():
            inbound_drones = []
            for drone in self.engine.drones.values():
                if drone.status in (DroneStatus.RETURNING, DroneStatus.DIVERTED):
                    dist = drone.position.distance_to(depot.position)
                    if dist < 3.0:  # Within 3 km
                        eta_seconds = (dist / (drone.speed_kmh / 3600)) if drone.speed_kmh > 0 else 999
                        inbound_drones.append((drone, eta_seconds, dist))

            if len(inbound_drones) > 1:
                # Sort by battery (lowest first = highest priority)
                inbound_drones.sort(key=lambda x: x[0].battery_charge)

                log = self.engine.emit_log(
                    self.AGENT_NAME,
                    f"⚠️ CONFLICT: {len(inbound_drones)} drones approaching {depot.name} simultaneously! "
                    f"Zero-hover sequencing engaged. "
                    f"Priority: {inbound_drones[0][0].name} (battery: {inbound_drones[0][0].battery_charge:.1f}%)",
                )
                logs.append(log)

                # Grant priority to lowest battery drone
                available_pads = [p for p in depot.pads if p.status == PadStatus.AVAILABLE]
                if available_pads and inbound_drones:
                    priority_drone = inbound_drones[0][0]
                    pad = available_pads[0]
                    pad.status = PadStatus.RESERVED
                    pad.reserved_for = priority_drone.id

                    log2 = self.engine.emit_log(
                        self.AGENT_NAME,
                        f"✅ {pad.id} reserved for {priority_drone.name} (priority: low battery). "
                        f"Other drones adjusted to hold speed for sequenced approach.",
                    )
                    logs.append(log2)

                    # Slow down other drones
                    for drone, _, _ in inbound_drones[1:]:
                        drone.speed_kmh *= 0.7  # Reduce speed for sequencing
                        log3 = self.engine.emit_log(
                            self.AGENT_NAME,
                            f"🐢 {drone.name} speed reduced to {drone.speed_kmh:.0f} km/h "
                            f"for sequenced approach. ETA adjusted.",
                        )
                        logs.append(log3)

        return logs

    def reserve_pad(self, depot_id: str, drone_id: str) -> bool:
        """Reserve a pad for a specific drone."""
        depot = self.engine.depots.get(depot_id)
        if not depot:
            return False

        for pad in depot.pads:
            if pad.status == PadStatus.AVAILABLE:
                pad.status = PadStatus.RESERVED
                pad.reserved_for = drone_id
                return True
        return False
