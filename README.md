# SkyGrid Enterprise ✈️

> **Autonomous Multi-Agent Drone Fleet & Depot Orchestrator**  
> AIconomy International AI Challenge 2026/27 — Competition Submission

[![Tests](https://img.shields.io/badge/tests-34%20passed-34d399)](backend/tests/test_core.py)
[![ML Model](https://img.shields.io/badge/ML%20R%C2%B2-0.9987-38bdf8)](docs/MODEL_CARD.md)
[![Python](https://img.shields.io/badge/python-3.13-a78bfa)](backend/requirements.txt)

---

## What It Does

SkyGrid orchestrates a 6-drone fleet across 3 depots in Greater Colombo, Sri Lanka.
Four specialised AI agents coordinate in real time:

| Agent | Role |
|---|---|
| **Dispatcher** | Assigns drones using composite scoring + ML-predicted mission cost |
| **Corridor** | Plans weather-aware A* flight corridors |
| **TAT-Depot** | Sequences zero-hover landings; resolves pad congestion |
| **Resolver** | Handles drop-zone obstacles and emergency battery diversions |

A machine learning model (GradientBoosting, R²=0.9987) predicts mission duration and energy consumption for candidate assignments, enabling smarter dispatch decisions.

---

## Quickstart (Demo)

```bash
# Terminal 1 — Backend
cd backend
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000

# Terminal 2 — Frontend
cd frontend
npm install
npm run dev
```

Open **http://localhost:5173** → click a Scenario → watch the fleet.

---

## Full Experiment (Reproducible)

```powershell
.\scripts\run_full_experiment.ps1
```

This will: install deps → run 34 tests → generate ML data → train models → run benchmarks → print results. Takes ~2–4 minutes.

---

## Benchmark Results (Simulation Only)

| Strategy | Delivery Rate | Energy/Delivery | Mean Time |
|---|---|---|---|
| Baseline (nearest drone) | 98.0% | 7.1% | 310 s |
| SkyGrid (rule-based) | 98.0% | 7.0% | 308 s |
| **AI-Assist (ML-informed)** | **98.0%** | **6.2%** | **303 s** |

*All results from simulation. Not validated on physical hardware.*

---

## Architecture

```
frontend/  React + Vite + Leaflet
backend/
  ├── main.py              FastAPI server + WebSocket broadcast
  ├── agents/              4 specialised agent modules
  ├── services/            Simulation engine, A* routing, weather
  ├── ml/                  Data generation, training, predictor
  ├── benchmarks/          3-strategy reproducible runner
  └── tests/               34 unit + integration tests
docs/
  ├── CURRENT_STATE_AUDIT.md        10 defects found + fixed
  ├── PROBLEM_AND_SCOPE.md          Problem context, boundaries
  ├── MODEL_CARD.md                 ML model documentation
  ├── ETHICS_AND_RESPONSIBLE_AI.md  Responsible AI statement
  ├── RISK_REGISTER.md              Risk tracking
  └── IMPLEMENTATION_REPORT.md     Full project report
results/
  ├── ml_metrics.json               Training and test metrics
  ├── benchmark_summary.csv         Per-strategy comparison
  └── benchmark_details.csv         Per-episode raw results
```

---

## Key Technical Features

- **10 defects identified and fixed** (see `docs/CURRENT_STATE_AUDIT.md`)
- **ML mission-cost predictor** with deterministic fallback (never overrides safety)
- **Reproducible benchmarks**: fixed seeds, 3 strategies, identical scenarios
- **Separation constraint monitoring**: 50 m minimum, logged as violations
- **Pre-flight battery feasibility gate**: dispatch only if battery ≥ round-trip cost + 20% reserve
- **Full reset fidelity**: SoH, motor hours, and charge cycles restored on reset
- **34 automated tests**, all passing

---

## Important Disclaimers

- All performance results are from **simulation only**
- The physics model is an **approximation**, not calibrated against hardware
- The ML model's high R² reflects approximation of the simulator, not real-world prediction
- This is a **research prototype**, not a certified operational system
- No real drones are controlled by this software

See `docs/ETHICS_AND_RESPONSIBLE_AI.md` for the full responsible AI statement.

---

## Documentation

| Document | Purpose |
|---|---|
| [IMPLEMENTATION_REPORT.md](docs/IMPLEMENTATION_REPORT.md) | Full project report |
| [MODEL_CARD.md](docs/MODEL_CARD.md) | ML model documentation |
| [CURRENT_STATE_AUDIT.md](docs/CURRENT_STATE_AUDIT.md) | Phase 1 audit |
| [PROBLEM_AND_SCOPE.md](docs/PROBLEM_AND_SCOPE.md) | Problem context |
| [ETHICS_AND_RESPONSIBLE_AI.md](docs/ETHICS_AND_RESPONSIBLE_AI.md) | Ethics statement |
| [RISK_REGISTER.md](docs/RISK_REGISTER.md) | Risk register |
| [SECURITY.md](SECURITY.md) | Security notes |
