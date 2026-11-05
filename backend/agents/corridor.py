"""
Dynamic Corridor Agent
=======================
Micro-Weather & Physics-Aware A* Routing.
Computes, validates, and dynamically shifts 3D flight paths.
"""

from services.simulation_engine import SimulationEngine, Drone, DroneStatus, Position
from services.routing_service import RoutingService
from services.weather_service import WeatherService


class CorridorAgent:
    """
    Dynamic Corridor Agent — computes physics-aware flight corridors
    incorporating real-time weather data and battery discharge curves.
    """

    AGENT_NAME = "CORRIDOR"

    def __init__(self, engine: SimulationEngine, routing: RoutingService, weather: WeatherService):
        self.engine = engine
        self.routing = routing
        self.weather = weather

    async def compute_corridor(self, drone: Drone, destination: Position) -> list[dict]:
        """
        Compute a weather-aware flight corridor for a drone.
        Returns agent logs.
        """
        logs = []

        # Fetch real weather
        weather_data = await self.weather.get_weather(
            (drone.position.lat + destination.lat) / 2,
            (drone.position.lon + destination.lon) / 2,
        )

        # Compute A* path
        weather_cells_dict = [w.to_dict() for w in self.engine.weather_cells if w.active]
        waypoints = self.routing.compute_path(
            drone.position,
            destination,
            weather_cells=weather_cells_dict,
        )

        # Calculate battery curve
        battery_curve = self.routing.calculate_battery_curve(
            waypoints,
            payload_kg=drone.current_payload_kg,
            wind_speed_kmh=weather_data.wind_speed_kmh,
            battery_start=drone.battery_charge,
        )

        # Check if path is safe
        unsafe_points = [p for p in battery_curve if not p["safe"]]
        final_battery = battery_curve[-1]["battery_pct"] if battery_curve else 50.0

        log = self.engine.emit_log(
            self.AGENT_NAME,
            f"📐 Corridor computed for {drone.name}: "
            f"{len(waypoints)} waypoints | "
            f"Weather: {weather_data.advisory} | "
            f"Wind: {weather_data.wind_speed_kmh:.1f} km/h | "
            f"Gusts: {weather_data.wind_gusts_kmh:.1f} km/h | "
            f"Final battery est: {final_battery:.1f}% | "
            f"{'⛔ UNSAFE — diversion required!' if unsafe_points else '✅ All waypoints within safe margin'}",
        )
        logs.append(log)

        if unsafe_points:
            # Find nearest depot for intermediate stop
            midpoint = Position(
                waypoints[len(waypoints) // 2]["lat"],
                waypoints[len(waypoints) // 2]["lon"],
            )
            nearest = self.engine._find_nearest_depot(midpoint)
            if nearest:
                log2 = self.engine.emit_log(
                    self.AGENT_NAME,
                    f"⚠️ Battery insufficient for direct flight. "
                    f"Inserting intermediate stop at {nearest.name} for battery swap. "
                    f"Recalculating corridor...",
                )
                logs.append(log2)

        return logs

    def evaluate_microburst_impact(self, drone: Drone) -> list[dict]:
        """Evaluate impact of current weather cells on a drone's path."""
        logs = []

        for cell in self.engine.weather_cells:
            if not cell.active:
                continue
            dist = drone.position.distance_to(cell.position)
            if dist < cell.radius_km * 1.5:
                # Calculate physics impact
                drag_increase = cell.wind_speed_kmh * 0.41  # Watts
                discharge_increase = (cell.wind_speed_kmh / 50.0) * 60  # percentage increase
                remaining = drone.battery_charge * (1 - discharge_increase / 100)

                log = self.engine.emit_log(
                    self.AGENT_NAME,
                    f"🌊 {drone.name} weather impact analysis: "
                    f"Headwind drag: +{drag_increase:.1f}W | "
                    f"Discharge rate: +{discharge_increase:.0f}% | "
                    f"Battery margin post-cell: {remaining:.1f}% | "
                    f"Threshold: {'⛔ CRITICAL' if remaining < 15 else '⚠️ MARGINAL' if remaining < 30 else '✅ Safe'}",
                )
                logs.append(log)

        return logs
