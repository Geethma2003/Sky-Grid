"""
Agent Orchestrator
===================
Coordinates all 4 specialized agents over a shared state graph.
Manages the simulation tick loop and WebSocket broadcasting.
"""

import asyncio
import json
import time
from typing import Callable, Awaitable

from services.simulation_engine import SimulationEngine
from services.routing_service import RoutingService
from services.weather_service import WeatherService
from agents.dispatcher import DispatcherAgent
from agents.corridor import CorridorAgent
from agents.turnaround import TurnaroundAgent
from agents.resolver import ResolverAgent


class AgentOrchestrator:
    """
    Central orchestrator that coordinates the 4-agent system,
    manages the simulation loop, and broadcasts state via WebSocket.
    """

    def __init__(self):
        self.engine = SimulationEngine()
        self.routing = RoutingService()
        self.weather = WeatherService()

        # Initialize agents
        self.dispatcher = DispatcherAgent(self.engine)
        self.corridor = CorridorAgent(self.engine, self.routing, self.weather)
        self.turnaround = TurnaroundAgent(self.engine)
        self.resolver = ResolverAgent(self.engine)

        self._running = False
        self._broadcast_fn: Callable[[dict], Awaitable[None]] | None = None
        self._tick_interval = 0.5  # 500ms ticks for smooth animation
        self._log_queue: list[dict] = []

    def set_broadcast(self, fn: Callable[[dict], Awaitable[None]]):
        """Set the WebSocket broadcast function."""
        self._broadcast_fn = fn

    async def start_loop(self):
        """Start the main simulation tick loop."""
        self._running = True
        while self._running:
            try:
                # Advance simulation
                new_logs = self.engine.tick(dt=self._tick_interval)

                # Run periodic agent checks (every 5 ticks = 2.5 seconds)
                if self.engine._tick_count % 5 == 0:
                    tat_logs = self.turnaround.check_pad_conflicts()
                    new_logs.extend(tat_logs)

                if self.engine._tick_count % 10 == 0:
                    resolver_logs = self.resolver.check_emergency_conditions()
                    new_logs.extend(resolver_logs)

                # Broadcast state
                if self._broadcast_fn:
                    state = self.engine.get_full_state()
                    state["new_logs"] = new_logs
                    await self._broadcast_fn(state)

                await asyncio.sleep(self._tick_interval)

            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"Orchestrator tick error: {e}")
                await asyncio.sleep(1.0)

    def stop_loop(self):
        """Stop the simulation loop."""
        self._running = False

    async def handle_command(self, command: str, data: dict | None = None) -> dict:
        """Handle commands from the frontend."""
        data = data or {}

        if command == "scenario_a":
            logs = self.engine.create_scenario_a()
            return {"status": "ok", "logs": logs}

        elif command == "scenario_b":
            logs = self.engine.create_scenario_b()
            return {"status": "ok", "logs": logs}

        elif command == "scenario_c":
            logs = self.engine.create_scenario_c()
            return {"status": "ok", "logs": logs}

        elif command == "chaos_pad":
            logs = self.engine.inject_pad_congestion()
            return {"status": "ok", "logs": logs}

        elif command == "chaos_wind":
            logs = self.engine.inject_microburst()
            return {"status": "ok", "logs": logs}

        elif command == "chaos_obstacle":
            logs = self.engine.inject_drop_obstacle()
            return {"status": "ok", "logs": logs}

        elif command == "reset":
            self.engine.reset_simulation()
            return {"status": "ok", "logs": []}

        elif command == "get_state":
            return {"status": "ok", "state": self.engine.get_full_state()}

        elif command == "get_weather":
            lat = data.get("lat", 6.9271)
            lon = data.get("lon", 79.8612)
            weather = await self.weather.get_weather(lat, lon)
            return {"status": "ok", "weather": weather.to_dict()}

        elif command == "fleet_report":
            logs = self.dispatcher.evaluate_fleet_readiness()
            logs.extend(self.turnaround.get_depot_status())
            return {"status": "ok", "logs": logs}

        else:
            return {"status": "error", "message": f"Unknown command: {command}"}
