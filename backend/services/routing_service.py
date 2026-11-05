"""
SkyGrid Enterprise - A* Routing Service
=========================================
Physics-aware A* pathfinding using NetworkX for flight corridor computation.
Incorporates wind vectors and battery discharge curves.

Bug fixes applied:
  D-001: Weather penalties no longer accumulate across successive calls.
         Base weights stored at build time; restored before each path search.
  D-002: Out-of-grid coordinates detected and logged; falls back to direct path.
"""

import math
import logging
import networkx as nx
from services.simulation_engine import Position

logger = logging.getLogger(__name__)


class RoutingService:
    """
    A* routing over a navigational grid, weighted by distance,
    wind penalty, and altitude constraints.

    The grid is 2-D (lat, lon). Altitude is assigned from a
    standardised climb/cruise/descend profile post-hoc. This is
    NOT a 4-D time-expanded planner; describe it accordingly.
    """

    # Grid extends ~8.8 km around center (20 nodes × 0.004° ≈ 440 m/step)
    GRID_SIZE = 20
    LAT_STEP = 0.004   # ≈ 440 m per grid step
    LON_STEP = 0.004
    CRUISE_ALT_M = 120.0

    def __init__(self, center_lat: float = 6.9271, center_lon: float = 79.8612):
        self.center_lat = center_lat
        self.center_lon = center_lon
        self.graph = nx.Graph()
        self._start_lat: float = 0.0
        self._start_lon: float = 0.0
        self._build_nav_grid()

    # ── Graph construction ─────────────────────────────────────────────

    def _build_nav_grid(self):
        """Build a navigational graph over the operational area.
        Base weights stored as edge attributes so they can be restored
        before each path search (fixes D-001).
        """
        self._start_lat = self.center_lat - (self.GRID_SIZE / 2) * self.LAT_STEP
        self._start_lon = self.center_lon - (self.GRID_SIZE / 2) * self.LON_STEP

        for i in range(self.GRID_SIZE):
            for j in range(self.GRID_SIZE):
                lat = self._start_lat + i * self.LAT_STEP
                lon = self._start_lon + j * self.LON_STEP
                self.graph.add_node((i, j), lat=lat, lon=lon)

        for i in range(self.GRID_SIZE):
            for j in range(self.GRID_SIZE):
                for di, dj in [(-1, 0), (1, 0), (0, -1), (0, 1),
                               (-1, -1), (-1, 1), (1, -1), (1, 1)]:
                    ni, nj = i + di, j + dj
                    if 0 <= ni < self.GRID_SIZE and 0 <= nj < self.GRID_SIZE:
                        n1 = self.graph.nodes[(i, j)]
                        n2 = self.graph.nodes[(ni, nj)]
                        dist = self._haversine(
                            n1["lat"], n1["lon"], n2["lat"], n2["lon"]
                        )
                        base = dist * (1.05 if abs(di) + abs(dj) == 2 else 1.0)
                        # Store base weight explicitly — never overwritten
                        self.graph.add_edge(
                            (i, j), (ni, nj),
                            weight=base,
                            base_weight=base,
                        )

    # ── Coordinate mapping ─────────────────────────────────────────────

    def _coord_to_node(self, lat: float, lon: float) -> tuple[int, int] | None:
        """Map a coordinate to the nearest grid node.

        Returns None if the coordinate lies outside the grid boundary
        (D-002 fix: caller must handle None).
        """
        i = round((lat - self._start_lat) / self.LAT_STEP)
        j = round((lon - self._start_lon) / self.LON_STEP)
        if not (0 <= i < self.GRID_SIZE and 0 <= j < self.GRID_SIZE):
            return None
        return (i, j)

    def _coord_to_node_clamped(self, lat: float, lon: float) -> tuple[int, int]:
        """Map a coordinate to the nearest grid node, clamping to grid boundary.
        Used only when a best-effort node is acceptable (heuristic, not routing).
        """
        i = max(0, min(self.GRID_SIZE - 1, round((lat - self._start_lat) / self.LAT_STEP)))
        j = max(0, min(self.GRID_SIZE - 1, round((lon - self._start_lon) / self.LON_STEP)))
        return (i, j)

    def _node_to_coord(self, node: tuple[int, int]) -> tuple[float, float]:
        data = self.graph.nodes[node]
        return (data["lat"], data["lon"])

    def is_in_grid(self, lat: float, lon: float) -> bool:
        """Return True if the coordinate falls within the navigational grid."""
        return self._coord_to_node(lat, lon) is not None

    # ── Path computation ───────────────────────────────────────────────

    def compute_path(
        self,
        start: Position,
        end: Position,
        weather_cells: list | None = None,
        cruise_alt: float = CRUISE_ALT_M,
    ) -> list[dict]:
        """
        Compute A* flight path from start to end.
        Returns list of waypoints with lat, lon, alt.

        D-001 fix: edge weights are reset from stored base_weight before
                   applying weather penalties, so penalties do not accumulate.
        D-002 fix: out-of-grid endpoints fall back to direct path with a warning.
        """
        start_node = self._coord_to_node(start.lat, start.lon)
        end_node = self._coord_to_node(end.lat, end.lon)

        # D-002: detect out-of-grid endpoints
        if start_node is None or end_node is None:
            logger.warning(
                "RoutingService: coordinate outside nav grid "
                "(start=%s, end=%s). Falling back to direct path.",
                (start.lat, start.lon), (end.lat, end.lon)
            )
            return self._direct_path(start, end, cruise_alt)

        if start_node == end_node:
            return [
                {"lat": start.lat, "lon": start.lon, "alt": cruise_alt},
                {"lat": end.lat, "lon": end.lon, "alt": 30.0},
            ]

        # D-001: reset edge weights to clean base values before penalising
        self._restore_base_weights()

        # Apply weather penalties to affected edges
        if weather_cells:
            self._apply_weather_penalties(weather_cells)

        try:
            path = nx.astar_path(
                self.graph,
                start_node,
                end_node,
                heuristic=self._heuristic,
                weight="weight",
            )
        except nx.NetworkXNoPath:
            logger.warning("RoutingService: no A* path found; using direct path.")
            return self._direct_path(start, end, cruise_alt)

        return self._path_to_waypoints(path, end, cruise_alt)

    def _restore_base_weights(self):
        """Reset all edge weights to their clean base values (D-001 fix)."""
        for u, v, data in self.graph.edges(data=True):
            data["weight"] = data["base_weight"]

    def _apply_weather_penalties(self, weather_cells: list):
        """Apply weather-cell penalties to nearby graph edges."""
        for cell in weather_cells:
            if not cell.get("active", True):
                continue
            cell_lat = cell["position"]["lat"]
            cell_lon = cell["position"]["lon"]
            radius = cell.get("radius_km", 2.0)
            wind = cell.get("wind_speed_kmh", 30.0)

            for node in self.graph.nodes():
                node_lat, node_lon = self._node_to_coord(node)
                dist = self._haversine(node_lat, node_lon, cell_lat, cell_lon)
                if dist < radius:
                    penalty = (1.0 - dist / radius) * (wind / 20.0)
                    for neighbor in self.graph.neighbors(node):
                        edge = self.graph[node][neighbor]
                        # Multiply from base, not from current (D-001 fix)
                        edge["weight"] = edge["base_weight"] * (1.0 + penalty)

    def _path_to_waypoints(
        self, path: list, end: Position, cruise_alt: float
    ) -> list[dict]:
        """Convert a node path to a waypoint list with altitude profile."""
        waypoints = []
        step = max(1, len(path) // 8)
        for idx in range(0, len(path), step):
            lat, lon = self._node_to_coord(path[idx])
            progress = idx / max(len(path) - 1, 1)
            if progress < 0.1:
                alt = cruise_alt * (progress / 0.1)
            elif progress > 0.85:
                alt = cruise_alt * ((1.0 - progress) / 0.15)
            else:
                alt = cruise_alt
            waypoints.append({
                "lat": round(lat, 6),
                "lon": round(lon, 6),
                "alt": round(max(30.0, alt), 1),
            })

        waypoints.append({
            "lat": round(end.lat, 6),
            "lon": round(end.lon, 6),
            "alt": 30.0,
        })
        return waypoints

    def _direct_path(self, start: Position, end: Position, cruise_alt: float) -> list[dict]:
        """Fallback direct path with altitude profile."""
        waypoints = []
        for i in range(8):
            t = (i + 1) / 8.0
            lat = start.lat + (end.lat - start.lat) * t
            lon = start.lon + (end.lon - start.lon) * t
            if t < 0.15:
                alt = cruise_alt * (t / 0.15)
            elif t > 0.85:
                alt = cruise_alt * ((1 - t) / 0.15)
            else:
                alt = cruise_alt
            waypoints.append({
                "lat": round(lat, 6),
                "lon": round(lon, 6),
                "alt": round(max(30.0, alt), 1),
            })
        return waypoints

    # ── Heuristic ──────────────────────────────────────────────────────

    def _heuristic(self, n1: tuple, n2: tuple) -> float:
        lat1, lon1 = self._node_to_coord(n1)
        lat2, lon2 = self._node_to_coord(n2)
        return self._haversine(lat1, lon1, lat2, lon2)

    # ── Static utilities ───────────────────────────────────────────────

    @staticmethod
    def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """Haversine great-circle distance in kilometres."""
        R = 6371.0
        lat1, lon1 = math.radians(lat1), math.radians(lon1)
        lat2, lon2 = math.radians(lat2), math.radians(lon2)
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
        return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    # ── Battery curve ──────────────────────────────────────────────────

    def calculate_battery_curve(
        self,
        waypoints: list[dict],
        payload_kg: float,
        wind_speed_kmh: float = 0.0,
        battery_start: float = 100.0,
    ) -> list[dict]:
        """
        Compute battery discharge curve along waypoints.
        Returns list of {waypoint_index, battery_pct, wh_per_km, safe}.

        Consumption model (approximate, not calibrated from physical hardware):
          base  = 2.8 Wh/km
          payload factor = 1 + (kg/5) * 0.3
          wind factor    = 1 + (wind_kmh/50) * 0.6
          altitude factor = 1 + (alt_diff_m/120) * 0.15

        The 15% threshold for "safe" is the same value used in the engine's
        emergency diversion trigger.
        """
        SAFE_THRESHOLD_PCT = 15.0
        BASE_WH_KM = 2.8

        curve = []
        battery = battery_start

        for i in range(len(waypoints)):
            if i == 0:
                curve.append({
                    "waypoint_index": 0,
                    "battery_pct": round(battery, 1),
                    "wh_per_km": 0.0,
                    "safe": battery > SAFE_THRESHOLD_PCT,
                })
                continue

            prev = waypoints[i - 1]
            curr = waypoints[i]
            dist = self._haversine(prev["lat"], prev["lon"], curr["lat"], curr["lon"])

            payload_factor = 1.0 + (payload_kg / 5.0) * 0.3
            wind_factor = 1.0 + (wind_speed_kmh / 50.0) * 0.6
            alt_diff = abs(curr.get("alt", 120.0) - prev.get("alt", 120.0))
            alt_factor = 1.0 + (alt_diff / 120.0) * 0.15

            wh_km = BASE_WH_KM * payload_factor * wind_factor * alt_factor
            consumed_pct = dist * wh_km
            battery = max(0.0, battery - consumed_pct)

            curve.append({
                "waypoint_index": i,
                "battery_pct": round(battery, 1),
                "wh_per_km": round(wh_km, 2),
                "safe": battery > SAFE_THRESHOLD_PCT,
            })

        return curve

    def estimate_route_battery_cost(
        self,
        start: Position,
        end: Position,
        payload_kg: float = 0.0,
        wind_speed_kmh: float = 0.0,
    ) -> float:
        """
        Quick estimate of battery consumption (% points) for a route.
        Used for pre-flight feasibility checks (fixes D-006).
        Returns estimated battery consumed as a positive percentage.
        """
        dist = start.distance_to(end)
        payload_factor = 1.0 + (payload_kg / 5.0) * 0.3
        wind_factor = 1.0 + (wind_speed_kmh / 50.0) * 0.6
        wh_km = 2.8 * payload_factor * wind_factor
        return dist * wh_km
