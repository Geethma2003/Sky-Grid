"""
Exception Resolver Agent
=========================
Human-on-the-Loop Interceptor.
Manages unstructured real-world anomalies at destination drop points.
"""

from services.simulation_engine import (
    SimulationEngine, Drone, DroneStatus, Order, OrderStatus
)


class ResolverAgent:
    """
    Exception Resolver Agent — evaluates delivery obstacles,
    attempts automated resolution, and escalates to human supervisor
    only when safety margins require it.
    """

    AGENT_NAME = "RESOLVER"
    SAFETY_THRESHOLD_BATTERY = 10.0  # Below this, escalate

    def __init__(self, engine: SimulationEngine):
        self.engine = engine

    def evaluate_drop_zone(self, drone: Drone, order: Order) -> list[dict]:
        """Evaluate the drop zone for obstacles and determine resolution."""
        logs = []

        if not self.engine.chaos_state.get("drop_zone_obstacle"):
            log = self.engine.emit_log(
                self.AGENT_NAME,
                f"✅ Drop zone clear for {drone.name} → {order.destination_label}. "
                f"LiDAR scan: No obstructions. Precision landing authorized.",
            )
            logs.append(log)
            return logs

        # Obstacle detected — evaluate resolution options
        log = self.engine.emit_log(
            self.AGENT_NAME,
            f"🚧 OBSTACLE at {order.destination_label}: "
            f"LiDAR scan detects tree canopy at estimated 8m AGL, "
            f"construction scaffolding at 12m AGL. "
            f"Direct landing: ❌ BLOCKED.",
        )
        logs.append(log)

        # Decision tree
        wind_ok = not self.engine.chaos_state.get("microburst")
        battery_ok = drone.battery_charge > 20

        if wind_ok and battery_ok:
            resolution = "WINCH_DROP"
            log2 = self.engine.emit_log(
                self.AGENT_NAME,
                f"🔧 Resolution: Precision winch-drop selected. "
                f"Wind check: ✅ PASS | Battery: ✅ {drone.battery_charge:.1f}% | "
                f"Deploying 3m tether from {drone.altitude_m:.0f}m AGL. "
                f"Package weight: {drone.current_payload_kg}kg — within winch capacity.",
            )
            logs.append(log2)
        elif battery_ok:
            resolution = "LOCKBOX_REROUTE"
            log2 = self.engine.emit_log(
                self.AGENT_NAME,
                f"🔄 Resolution: Rerouting to nearest company lockbox. "
                f"Wind conditions marginal for winch — safety first. "
                f"Lockbox location: 0.3 km east. Customer will be notified via app.",
            )
            logs.append(log2)
        else:
            resolution = "ESCALATE"
            log2 = self.engine.emit_log(
                self.AGENT_NAME,
                f"🚨 ESCALATION REQUIRED: Battery at {drone.battery_charge:.1f}% "
                f"and wind conditions prevent automated resolution. "
                f"Escalating to human fleet supervisor. "
                f"1:100 operator ratio maintained — this is exception #1 of 100.",
            )
            logs.append(log2)

        return logs

    def check_emergency_conditions(self) -> list[dict]:
        """Check all active drones for emergency conditions."""
        logs = []

        for drone in self.engine.drones.values():
            if drone.status in (DroneStatus.IDLE, DroneStatus.BATTERY_SWAP):
                continue

            # Battery emergency
            if drone.battery_charge < self.SAFETY_THRESHOLD_BATTERY:
                log = self.engine.emit_log(
                    self.AGENT_NAME,
                    f"🚨 EMERGENCY: {drone.name} battery CRITICAL at {drone.battery_charge:.1f}%! "
                    f"Below {self.SAFETY_THRESHOLD_BATTERY}% safety threshold. "
                    f"Initiating forced emergency landing protocol.",
                )
                logs.append(log)

                drone.status = DroneStatus.EMERGENCY
                # Find nearest depot
                nearest = self.engine._find_nearest_depot(drone.position)
                if nearest:
                    drone.waypoints = self.engine._generate_direct_waypoints(
                        drone.position, nearest.position
                    )
                    drone.waypoint_index = 0
                    drone.route_color = "#ff0000"

            # Motor hours warning
            if drone.motor_hours > 700:
                if drone.motor_hours % 50 < 1:  # Log periodically
                    log = self.engine.emit_log(
                        self.AGENT_NAME,
                        f"⚙️ Maintenance advisory: {drone.name} motor hours at {drone.motor_hours:.0f}h. "
                        f"Scheduled maintenance due at 800h.",
                    )
                    logs.append(log)

        return logs
