# SkyGrid Enterprise — Current State Audit

**Audit Date:** 2026-10-30  
**Version inspected:** workspace snapshot at audit date

---

## 1. Existing Features That Work

| Feature | File(s) | Notes |
|---|---|---|
| FastAPI REST + WebSocket server | `backend/main.py` | Correct lifespan, dead-client pruning |
| Simulation tick loop (0.5 s) | `orchestrator.py` | Stable async loop |
| Drone movement along waypoints | `simulation_engine.py` | Haversine interpolation |
| Battery discharge model | `simulation_engine.py` | Base + weather + payload factors |
| A* routing over 20x20 grid | `routing_service.py` | NetworkX, 8-connectivity |
| Battery curve prediction | `routing_service.py` | Per-waypoint state returned |
| Three demo scenarios | `simulation_engine.py` | A (peak), B (milk-run), C (medical) |
| Chaos injection | `simulation_engine.py` | Pad/wind/obstacle with timers |
| Open-Meteo weather fetch | `weather_service.py` | Keyless, 5-min cache, fallback |
| Agent log system | `simulation_engine.py` | Keeps last 200 entries |
| React + Vite + Leaflet frontend | `frontend/src/` | Dark-mode map, drone icons |
| Depot pad status tracking | `simulation_engine.py` | Four pad states |
| Emergency battery diversion | `simulation_engine.py` | Triggers at < 15% |
| Triangular milk-run routing | `simulation_engine.py` | `triangular_target` field |

---

## 2. Defects Confirmed by Code Inspection

### D-001 — Weather penalty accumulates on graph edges across calls (HIGH)
**File:** `routing_service.py` lines 100-117  
`compute_path()` modifies `edge["weight"]` in-place. Subsequent calls re-apply the penalty on the already-penalised weight, so weather costs compound indefinitely across path searches.  
**Fix:** Store clean base weights at graph build time; restore before each A* call.

### D-002 — Out-of-grid coordinates silently snapped to border nodes (MEDIUM)
**File:** `routing_service.py` lines 68-71  
Any destination outside the ~8.8 km grid is clamped to a border node with no warning, producing a wrong route.  
**Fix:** Detect and warn; fall back to direct path for out-of-grid coords.

### D-003 — Reset does not restore original battery SoH or motor hours (LOW)
**File:** `simulation_engine.py` lines 1184-1222  
`reset_simulation()` restores charge to 100% but preserves degraded SoH and motor hours across resets.  
**Fix:** Save original drone specs at init; restore on reset.

### D-004 — Pre-reserved return pad never released on divert (MEDIUM)
**File:** `simulation_engine.py:_dispatch_drone` lines 1022-1034  
Pad reserved at dispatch stays RESERVED permanently if the drone is diverted to a different depot.  
**Fix:** Release pad tied to drone ID when drone is diverted away.

### D-005 — `pad_congestion` flag not cleared when no alt depot found (LOW)
**File:** `simulation_engine.py` line 704  
Flag is cleared only inside the "alt found" branch, leaving it permanently true if no alt is available.  
**Fix:** Use a TTL timer to auto-clear the flag.

### D-006 — Dispatch battery gate does not account for route length (MEDIUM)
**File:** `dispatcher.py` line 59  
`battery_charge > 30` allows dispatch regardless of route distance; drone may run out mid-flight.  
**Fix:** Check battery against estimated route consumption before accepting.

### D-007 — Emergency diversion arrival battery estimate is a magic constant (LOW)
**File:** `simulation_engine.py` line 515  
Log shows `drone.battery_charge - 3` — unrelated to actual distance or consumption.  
**Fix:** Compute from distance and per-km consumption rate.

### D-008 — Random seed not controlled in scenario waypoint generation (MEDIUM)
**File:** `simulation_engine.py:_generate_waypoints` lines 781-782  
`random.uniform` used with no seed; each run produces different paths, preventing reproducibility.  
**Fix:** Accept optional seed; use `random.Random(seed)`.

### D-009 — `_force_pad_clear` can double-book OCCUPIED pads (MEDIUM)
**File:** `simulation_engine.py` lines 731-734  
Force-clear grants OCCUPIED pads to waiting drones without checking existing occupant.  
**Fix:** Only grant pads with status AVAILABLE.

### D-010 — No minimum separation constraint enforced between drones (HIGH)
No horizontal separation check exists. Drones can be co-located with no warning or intervention.  
**Fix:** Add 50 m minimum horizontal separation check in tick loop.

---

## 3. Architectural Limitations

| Area | Limitation |
|---|---|
| Architecture | Centrally orchestrated. Agents share mutable `SimulationEngine` state. Not decentralised. |
| Routing | 2D grid; altitude assigned post-hoc. Not a 4D planner. |
| Weather integration | Open-Meteo fetched for logging only; not used for A* edge weights at dispatch time. |
| ML | No machine-learning component. Scoring is hand-crafted heuristic. |
| Benchmarking | No baseline strategy, no comparative evaluation, no reproducible runner. |
| Testing | No automated tests of any kind. |
| Seed management | No global seed control for reproducible experiments. |
| Safety | Simulation constraints only; no certified collision avoidance. |

---

## 4. Gap vs. Competition Criteria

| Criterion | Gap |
|---|---|
| Innovation | No ML, no novel coordination |
| AI use | No genuine ML component |
| Dataset | No dataset |
| Model design | No model or training pipeline |
| Evaluation | No comparative evaluation framework |
| System quality | No tests, missing error handling |
| Presentation | No experiment dashboard or model info panel |

---

## 5. Prioritised Fixes

| Priority | ID | Fix |
|---|---|---|
| P0 | D-001 | Fix weather edge-weight accumulation |
| P0 | D-010 | Add separation constraint check |
| P1 | D-002 | Handle out-of-grid coordinates |
| P1 | D-004 | Release pad on divert |
| P1 | D-006 | Pre-flight battery feasibility |
| P1 | D-008 | Controlled random seed |
| P2 | D-003 | Full state restore on reset |
| P2 | D-005 | Fix pad_congestion flag |
| P2 | D-007 | Correct emergency ETA estimate |
| P2 | D-009 | Protect OCCUPIED pads |
