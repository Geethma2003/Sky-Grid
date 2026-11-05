# SkyGrid Enterprise — Risk Register

**Version:** 1.0 | **Date:** 2026-10-30 | **Review cadence:** Per major release

Risk likelihood: **L**=Low, **M**=Medium, **H**=High  
Risk impact: **L**=Low, **M**=Medium, **H**=High, **C**=Critical

---

## Technical Risks

| ID | Risk | L | I | Rating | Mitigation | Status |
|---|---|---|---|---|---|---|
| TR-01 | Weather penalty accumulates on graph edges across calls | — | — | **RESOLVED** | Base weights stored; restored at start of each A* call (D-001) | ✅ Fixed |
| TR-02 | Out-of-grid coordinates silently produce wrong routes | — | — | **RESOLVED** | Detected; falls back to direct path with warning (D-002) | ✅ Fixed |
| TR-03 | Reset does not restore original drone SoH/motor hours | — | — | **RESOLVED** | Original specs saved at init; fully restored on reset (D-003) | ✅ Fixed |
| TR-04 | Pre-reserved pad never released when drone diverted | — | — | **RESOLVED** | `_release_pad_for_drone()` called before divert (D-004) | ✅ Fixed |
| TR-05 | Pad congestion flag not cleared without alt depot | — | — | **RESOLVED** | TTL timer clears flag regardless of outcome (D-005) | ✅ Fixed |
| TR-06 | Dispatch gate ignores route length | — | — | **RESOLVED** | Pre-flight feasibility check using distance estimate (D-006) | ✅ Fixed |
| TR-07 | Emergency ETA battery estimate is a magic constant | — | — | **RESOLVED** | Computed from distance × consumption rate (D-007) | ✅ Fixed |
| TR-08 | No seed control in waypoint generation | — | — | **RESOLVED** | `_generate_waypoints(seed=)` parameter added (D-008) | ✅ Fixed |
| TR-09 | `_force_pad_clear` can double-book OCCUPIED pads | — | — | **RESOLVED** | Only grants AVAILABLE pads (D-009) | ✅ Fixed |
| TR-10 | No separation constraint monitoring | — | — | **RESOLVED** | 50 m check every 10 ticks; logged as violations (D-010) | ✅ Fixed |
| TR-11 | Async tick loop and command handler share mutable state | M | M | **Medium** | Acceptable under asyncio single-thread model; add asyncio.Lock if threading introduced | Open |
| TR-12 | ML model trained on synthetic data only | H | M | **Medium** | Disclosed in MODEL_CARD, predictor, and ethics doc; deterministic fallback always available | Open |
| TR-13 | No input validation on REST command endpoint | M | M | **Medium** | Allowlist of commands enforced in main.py | ✅ Fixed |
| TR-14 | WebSocket broadcasts can include large payloads | L | L | **Low** | Logs capped at 200 entries; state JSON typically < 20 KB | Monitored |
| TR-15 | CORS configured allow-all | L | L | **Low** | Acceptable for development/demo; restrict in production | Open |
| TR-16 | No rate limiting on API endpoints | L | M | **Low** | Acceptable for demo; add if public deployment planned | Open |
| TR-17 | ML model inference may be slow for large fleets | L | L | **Low** | Gradient Boosting inference < 5 ms per call; logged | Monitored |
| TR-18 | Battery model not calibrated against real hardware | H | M | **Medium** | Clearly disclosed as simulation approximation | Open |

---

## Safety Risks

| ID | Risk | L | I | Rating | Mitigation | Status |
|---|---|---|---|---|---|---|
| SR-01 | ML model overrides safety constraints | — | — | **RESOLVED** | Hard constraints enforced by dispatcher; ML cannot override | ✅ Fixed |
| SR-02 | Drone dispatched with insufficient battery | — | — | **RESOLVED** | Pre-flight feasibility gate (D-006); 20% reserve enforced | ✅ Fixed |
| SR-03 | Emergency diversion uses incorrect arrival battery estimate | — | — | **RESOLVED** | Estimate uses distance × consumption model (D-007) | ✅ Fixed |
| SR-04 | Co-located drones undetected | — | — | **RESOLVED** | Separation check every 10 ticks; violations logged (D-010) | ✅ Fixed |
| SR-05 | Real drones operated by this system | — | — | **NOT APPLICABLE** | System controls only simulation | N/A |
| SR-06 | Weather service outage causes unsafe routing | M | M | **Medium** | Fallback to static weather defaults; last-known-good cached 5 min | ✅ Mitigated |

---

## Operational Risks

| ID | Risk | L | I | Rating | Mitigation | Status |
|---|---|---|---|---|---|---|
| OR-01 | Results not reproducible between runs | — | — | **RESOLVED** | Fixed seeds in data gen, training, benchmarks, waypoints (D-008) | ✅ Fixed |
| OR-02 | Benchmark results misinterpreted as real-world evidence | M | H | **High** | All result files include `note` field; docs clearly disclaim simulation-only | ✅ Mitigated |
| OR-03 | Competition judges cannot run the project | M | H | **High** | `scripts/run_full_experiment.ps1` provides one-click reproducibility | ✅ Mitigated |
| OR-04 | Frontend WebSocket fails silently | M | L | **Low** | Auto-reconnect every 2 s; connection badge visible to user | ✅ Fixed |
| OR-05 | Backend fails to start (import errors) | M | H | **High** | Backend smoke test in CI (`python -c "from main import app"`) | ✅ Tested |

---

## Schedule & Scope Risks

| ID | Risk | L | I | Rating | Mitigation |
|---|---|---|---|---|---|
| SS-01 | All 12 phases not completed before submission | M | H | **High** | Priority ordering: defect fixes > ML > benchmarks > docs. All core phases complete. |
| SS-02 | Additional feature creep delays competition docs | M | M | **Medium** | Remaining effort is documentation only; no new code features. |

---

## Residual Risks Accepted

| Risk | Justification |
|---|---|
| Physics model not calibrated against hardware | Would require physical drone + controlled test environment; out of scope |
| No real-time 4D path planning | Full 4D (lat, lon, alt, time) A* was out of scope for this cycle |
| No regulatory compliance | Research and competition prototype only |
| Synthetic ML training data | Clearly disclosed; real data collection not feasible in timeframe |
