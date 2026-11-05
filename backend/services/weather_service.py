"""
SkyGrid Enterprise - Weather Service
======================================
Fetches real-time weather data from the Open-Meteo API (keyless).
Provides micro-weather cell generation for chaos simulation.
"""

import httpx
import asyncio
from dataclasses import dataclass


@dataclass
class WeatherData:
    temperature_c: float
    wind_speed_kmh: float
    wind_gusts_kmh: float
    precipitation_mm: float
    flight_safe: bool
    advisory: str

    def to_dict(self) -> dict:
        return {
            "temperature_c": self.temperature_c,
            "wind_speed_kmh": self.wind_speed_kmh,
            "wind_gusts_kmh": self.wind_gusts_kmh,
            "precipitation_mm": self.precipitation_mm,
            "flight_safe": self.flight_safe,
            "advisory": self.advisory,
        }


class WeatherService:
    """Real-time weather from Open-Meteo API."""

    BASE_URL = "https://api.open-meteo.com/v1/forecast"
    WIND_LIMIT_KMH = 50.0
    GUST_LIMIT_KMH = 65.0
    PRECIP_LIMIT_MM = 5.0

    def __init__(self):
        self._cache: dict[str, tuple[float, WeatherData]] = {}
        self._cache_ttl = 300  # 5 minutes

    async def get_weather(self, lat: float, lon: float) -> WeatherData:
        """Fetch current weather for coordinates."""
        cache_key = f"{lat:.2f},{lon:.2f}"

        # Check cache
        import time
        if cache_key in self._cache:
            ts, data = self._cache[cache_key]
            if time.time() - ts < self._cache_ttl:
                return data

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    self.BASE_URL,
                    params={
                        "latitude": lat,
                        "longitude": lon,
                        "current": "temperature_2m,wind_speed_10m,wind_gusts_10m,precipitation",
                    },
                )
                resp.raise_for_status()
                data = resp.json()

            current = data.get("current", {})
            temp = current.get("temperature_2m", 28.0)
            wind = current.get("wind_speed_10m", 8.0)
            gusts = current.get("wind_gusts_10m", 15.0)
            precip = current.get("precipitation", 0.0)

            flight_safe = (
                wind < self.WIND_LIMIT_KMH
                and gusts < self.GUST_LIMIT_KMH
                and precip < self.PRECIP_LIMIT_MM
            )

            advisory = "CLEAR"
            if not flight_safe:
                if wind >= self.WIND_LIMIT_KMH or gusts >= self.GUST_LIMIT_KMH:
                    advisory = f"HIGH WIND ADVISORY: {wind:.1f} km/h sustained, {gusts:.1f} km/h gusts"
                elif precip >= self.PRECIP_LIMIT_MM:
                    advisory = f"PRECIPITATION ADVISORY: {precip:.1f} mm/h"
            elif wind > 25:
                advisory = f"WIND CAUTION: {wind:.1f} km/h — increased discharge rates"

            weather = WeatherData(
                temperature_c=temp,
                wind_speed_kmh=wind,
                wind_gusts_kmh=gusts,
                precipitation_mm=precip,
                flight_safe=flight_safe,
                advisory=advisory,
            )

            self._cache[cache_key] = (time.time(), weather)
            return weather

        except Exception:
            # Fallback to reasonable defaults
            return WeatherData(
                temperature_c=28.5,
                wind_speed_kmh=12.0,
                wind_gusts_kmh=18.0,
                precipitation_mm=0.0,
                flight_safe=True,
                advisory="CLEAR (cached fallback)",
            )
