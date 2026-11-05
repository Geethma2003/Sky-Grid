# SkyGrid Enterprise — Ethics & Responsible AI Statement

**Version:** 1.0 | **Date:** 2026-10-30

---

## 1. Purpose of This Document

This document records how the team has considered ethical implications of the
SkyGrid Enterprise system throughout its design and implementation.
It is written in accordance with competition evaluation criteria that assess
responsible and appropriate use of AI.

---

## 2. What Kind of AI Is Being Used

SkyGrid uses two types of automated decision-making:

| Component | Type | Decisions Made |
|---|---|---|
| `DispatcherAgent` | Rule-based heuristic | Which drone to assign to an order |
| `CorridorAgent` | Graph algorithm (A*) | Which flight path to use |
| `TurnaroundAgent` | Rule-based | Which landing pad to allocate |
| `ResolverAgent` | Rule-based | How to respond to obstacles/battery emergencies |
| `MissionCostPredictor` | ML (GradientBoosting) | Predict mission time and energy cost |

The ML model **ranks candidate assignments** but does not autonomously execute
any dispatch. All dispatch decisions pass through hard safety gates enforced
by the rule-based dispatcher before any drone is moved.

---

## 3. Transparency

### 3a. Decision Logging
Every agent decision is logged with:
- Timestamp
- Agent name
- Human-readable rationale (e.g., "Battery too low; emergency divert to Alpha Hub")
- Drone and order identifiers

No decision is made silently. All 200 most recent log entries are visible in
the frontend agent log panel in real time.

### 3b. Model Transparency
- The ML model's architecture, training data, features, metrics, and limitations
  are documented in `docs/MODEL_CARD.md`.
- Feature importances are saved to `results/ml_feature_importance.json`.
- The model cannot override hard safety constraints (see Section 5).

### 3c. Uncertainty Disclosure
When the ML model is unavailable or produces implausible predictions,
the system falls back to deterministic computation and marks the result
`used_model: false`. This is surfaced in the API response and frontend badge.

---

## 4. Fairness

### 4a. Order Prioritisation
Medical (`MEDICAL`) and critical (`CRITICAL`) priority orders are always
processed first in the dispatch queue, independent of order arrival time.
This is by design: the scenario targets healthcare logistics where delayed
medical supplies can have life-safety consequences.

### 4b. Fleet Allocation
Drone assignment uses composite scoring that balances:
- Battery state-of-health (SoH) — to avoid degrading already-worn batteries
- Available charge — to ensure mission feasibility
- Payload match — to reduce unnecessary weight
- Depot proximity — to reduce deadhead distance

No individual drone is permanently preferred; all idle, eligible drones
compete on equal scoring criteria.

### 4c. Training Data Representation
The ML training dataset covers a range of:
- Battery levels (35–100%)
- Wind speeds (0–55 km/h)
- Payload weights (0.5–8 kg)
- All four priority classes
- Multiple depot origins

No priority class is under-represented in the training data.

---

## 5. Safety and Human Oversight

### 5a. Hard Constraints That Cannot Be Overridden by ML

| Constraint | Threshold | Enforced By |
|---|---|---|
| Battery reserve on arrival | ≥ 20 % | Dispatcher + ML Predictor |
| Emergency diversion trigger | < 15 % battery | Simulation engine |
| Minimum separation logging | < 50 m | Simulation engine (logged) |
| Max payload | Per-drone spec | Dispatcher |
| Implausible prediction gate | time ≤ 0 or > 7200 s | Predictor fallback |

### 5b. Human Oversight
- This is a **simulation and research prototype**, not an operational system.
- All "autonomous" decisions are within a simulated environment.
- No real drones are controlled.
- A human operator using the frontend can monitor all activity in real time
  and trigger resets or emergency scenarios manually.

### 5c. Fail-Safe Behaviour
- If the weather service fails → static fallback weather data is used.
- If the ML model fails → deterministic physics formula is used.
- If WebSocket disconnects → client auto-reconnects, no state is lost.

---

## 6. Privacy

No personal data is collected or processed.

- Weather queries use geographic coordinates only (no user IDs).
- Order destinations are randomly generated in simulation (no real addresses).
- No cookies, user accounts, or tracking are implemented.

---

## 7. Environmental Considerations

Drone delivery can reduce ground transport emissions in appropriate scenarios.
However, this system makes no life-cycle assessment claims. The simulation
does not model:
- Drone manufacturing carbon footprint
- Charging energy source (renewable vs. grid)
- Battery disposal
- Noise pollution

Any environmental benefit claims would require independent analysis.

---

## 8. Limitations We Actively Disclose

| Limitation | Where Documented |
|---|---|
| Synthetic training data only | MODEL_CARD.md, predictor.py, data_generation.py |
| Real-world accuracy unvalidated | MODEL_CARD.md, PROBLEM_AND_SCOPE.md |
| Not certified collision avoidance | simulation_engine.py (D-010 comment) |
| Not regulatory compliant | PROBLEM_AND_SCOPE.md |
| Physics model approximations | routing_service.py, simulation_engine.py docstrings |
| Healthcare use case is scenario only | PROBLEM_AND_SCOPE.md |

---

## 9. AI Tool Use Disclosure

This project was developed with AI coding assistance (Google Antigravity IDE).
AI tools were used for:
- Code generation assistance and refactoring
- Documentation drafting
- Test case generation suggestions

All generated code has been reviewed, tested (34 automated tests), and
validated by the project team. The design decisions, architecture, and
research framing are the team's own work.

---

## 10. Responsible Development Commitments

1. We do not misrepresent simulation results as real-world performance data.
2. We do not claim regulatory compliance or safety certification.
3. We do not suppress negative benchmark results (all three strategies
   produce comparable delivery rates; this is reported honestly).
4. We document all known defects and their fixes transparently.
5. We make reproducibility possible via fixed seeds and documented scripts.
