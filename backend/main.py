"""
SkyGrid Enterprise — FastAPI Backend
======================================
Main server with REST endpoints, WebSocket telemetry, benchmark API,
and ML model info endpoints.

Security notes:
  - CORS configured for development (allow all). Restrict in production.
  - No API keys required for core functionality.
  - Health check available at /api/health.
"""

import asyncio
import json
import os
import sys
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# Add parent to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agents.orchestrator import AgentOrchestrator


# ── Request models ────────────────────────────────────────────────────

class BenchmarkRequest(BaseModel):
    scenarios: int = Field(default=5, ge=1, le=50, description="Number of test scenarios")
    orders: int = Field(default=5, ge=1, le=20, description="Orders per scenario")
    seed: int = Field(default=42, ge=0, description="Random seed for reproducibility")
    strategies: list[str] = Field(
        default=["baseline", "skygrid", "ai_assist"],
        description="Strategies to compare"
    )


# ── WebSocket Manager ─────────────────────────────────────────────────

class ConnectionManager:
    """Manages WebSocket connections for real-time broadcast."""

    def __init__(self):
        self.active: list[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active.append(ws)

    def disconnect(self, ws: WebSocket):
        if ws in self.active:
            self.active.remove(ws)

    async def broadcast(self, data: dict):
        dead = []
        message = json.dumps(data, default=str)
        for ws in self.active:
            try:
                await ws.send_text(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


manager = ConnectionManager()
orchestrator = AgentOrchestrator()
sim_task: asyncio.Task | None = None


# ── Lifespan ──────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    global sim_task
    # Start simulation loop
    orchestrator.set_broadcast(manager.broadcast)
    sim_task = asyncio.create_task(orchestrator.start_loop())
    print("[SkyGrid] Simulation Engine ONLINE")
    yield
    # Shutdown
    orchestrator.stop_loop()
    if sim_task:
        sim_task.cancel()
        try:
            await sim_task
        except asyncio.CancelledError:
            pass
    print("[SkyGrid] Simulation Engine OFFLINE")


# ── App ───────────────────────────────────────────────────────────────

app = FastAPI(
    title="SkyGrid Enterprise API",
    description="Autonomous Multi-Agent Fleet & Depot Orchestrator",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── REST Endpoints ────────────────────────────────────────────────────

@app.get("/")
async def root():
    return {
        "name": "SkyGrid Enterprise",
        "version": "2.0.0",
        "status": "operational",
        "agents": ["DISPATCHER", "CORRIDOR", "TAT-DEPOT", "RESOLVER"],
        "ml_status": "available" if _get_ml_status().get("model_available") else "fallback",
    }


@app.get("/api/health")
async def health_check():
    """Health check endpoint for readiness probes."""
    return {
        "status": "healthy",
        "uptime_ticks": orchestrator.engine._tick_count,
        "active_drones": sum(
            1 for d in orchestrator.engine.drones.values()
            if d.status.value != "idle"
        ),
        "websocket_clients": len(manager.active),
        "ml_model_loaded": _get_ml_status().get("model_available", False),
    }


@app.get("/api/state")
async def get_state():
    return orchestrator.engine.get_full_state()


@app.get("/api/weather")
async def get_weather(lat: float = 6.9271, lon: float = 79.8612):
    weather = await orchestrator.weather.get_weather(lat, lon)
    return weather.to_dict()


@app.post("/api/command/{command}")
async def run_command(command: str):
    # Validate command is in allowed set
    allowed = {
        "scenario_a", "scenario_b", "scenario_c",
        "chaos_pad", "chaos_wind", "chaos_obstacle",
        "reset", "get_state", "get_weather", "fleet_report",
    }
    if command not in allowed:
        raise HTTPException(status_code=400, detail=f"Unknown command: {command}")
    result = await orchestrator.handle_command(command)
    return result


@app.post("/api/reset")
async def reset():
    orchestrator.engine.reset_simulation()
    return {"status": "ok"}


# ── ML Model Info ─────────────────────────────────────────────────────

def _get_ml_status() -> dict:
    try:
        from ml.predictor import get_predictor
        return get_predictor().status()
    except Exception:
        return {"model_available": False, "note": "ML module not loaded"}


@app.get("/api/model")
async def get_model_info():
    """Return ML model metadata for the frontend model-info panel."""
    status = _get_ml_status()
    # Load metrics if available
    metrics_path = os.path.join(os.path.dirname(__file__), "..", "results", "ml_metrics.json")
    metrics = {}
    try:
        with open(metrics_path) as f:
            metrics = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        pass

    return {
        **status,
        "metrics": metrics.get("models", {}).get(metrics.get("selected_model", ""), {}),
        "selected_model": metrics.get("selected_model"),
        "dataset_size": metrics.get("n_train", 0) + metrics.get("n_val", 0) + metrics.get("n_test", 0),
    }


# ── Benchmark API ─────────────────────────────────────────────────────

@app.post("/api/benchmark")
async def run_benchmark(req: BenchmarkRequest):
    """
    Run benchmark comparison in a background thread.
    Returns results when complete (may take seconds).
    """
    try:
        from benchmarks.runner import run_batch, save_results, Strategy

        strategies = [Strategy(s) for s in req.strategies if s in [e.value for e in Strategy]]
        if not strategies:
            raise HTTPException(status_code=400, detail="No valid strategies specified")

        seeds = list(range(req.seed, req.seed + req.scenarios))

        config = {
            "n_scenarios": req.scenarios,
            "n_orders": req.orders,
            "base_seed": req.seed,
            "strategies": [s.value for s in strategies],
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }

        # Run in executor to not block the event loop
        import concurrent.futures
        loop = asyncio.get_event_loop()
        with concurrent.futures.ThreadPoolExecutor() as pool:
            results = await loop.run_in_executor(
                pool,
                lambda: run_batch(req.scenarios, req.orders, seeds, strategies),
            )

        save_results(results, config)

        # Return summary
        from dataclasses import asdict
        return {
            "status": "ok",
            "n_episodes": len(results),
            "results": [asdict(r) for r in results],
        }

    except ImportError as e:
        raise HTTPException(status_code=500, detail=f"Benchmark module not available: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/benchmark/results")
async def get_benchmark_results():
    """Return last benchmark results from CSV."""
    results_dir = os.path.join(os.path.dirname(__file__), "..", "results")
    summary_path = os.path.join(results_dir, "benchmark_summary.csv")
    details_path = os.path.join(results_dir, "benchmark_details.csv")
    config_path = os.path.join(results_dir, "experiment_config.json")

    data: dict = {"summary": [], "details": [], "config": {}}
    try:
        import csv
        if os.path.exists(summary_path):
            with open(summary_path, newline="") as f:
                data["summary"] = list(csv.DictReader(f))
        if os.path.exists(details_path):
            with open(details_path, newline="") as f:
                data["details"] = list(csv.DictReader(f))
        if os.path.exists(config_path):
            with open(config_path) as f:
                data["config"] = json.load(f)
    except Exception as e:
        data["error"] = str(e)

    return data


# ── WebSocket ─────────────────────────────────────────────────────────

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await manager.connect(ws)
    print(f"[WS] Client connected. Active connections: {len(manager.active)}")

    # Send initial state
    try:
        state = orchestrator.engine.get_full_state()
        state["new_logs"] = []
        await ws.send_text(json.dumps(state, default=str))
    except Exception:
        pass

    try:
        while True:
            data = await ws.receive_text()
            try:
                msg = json.loads(data)
                command = msg.get("command", "")
                payload = msg.get("data", {})
                result = await orchestrator.handle_command(command, payload)

                # Send command result back
                await ws.send_text(json.dumps({
                    "type": "command_result",
                    "command": command,
                    **result,
                }, default=str))

            except json.JSONDecodeError:
                await ws.send_text(json.dumps({"error": "Invalid JSON"}))

    except WebSocketDisconnect:
        manager.disconnect(ws)
        print(f"[WS] Client disconnected. Active connections: {len(manager.active)}")
    except Exception:
        manager.disconnect(ws)
