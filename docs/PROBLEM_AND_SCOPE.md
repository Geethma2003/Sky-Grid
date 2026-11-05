# SkyGrid Enterprise — Problem Statement and Scope

## 1. Problem Context

Reliable last-mile delivery in Sri Lanka is hampered by road congestion,
infrastructure limitations in peri-urban areas, and time-critical healthcare logistics.
Autonomous drone fleets offer a potential supplement to ground transport,
particularly for urgent healthcare supply (blood products, medications, diagnostic samples)
between hospitals and satellite clinics in the Greater Colombo area.

**This is a proposed application scenario for research and demonstration purposes.**
No institutional partnership, operational approval, or real-world deployment exists.
All performance figures are derived from simulation.

---

## 2. Primary Users and Intended Beneficiaries

| User | Role |
|---|---|
| Fleet operator | Human supervisor overseeing automated dispatch decisions |
| Healthcare logistics coordinator | Requests and tracks urgent medical deliveries |
| Drone maintenance engineer | Reviews fleet SoH and maintenance advisories |
| Competition judges / researchers | Evaluates the AI system's decisions and performance |

**Intended beneficiaries (scenario):**
- Patients requiring time-critical medical supplies across facilities
- Hospital staff needing reliable supply-chain visibility
- Fleet operators managing multiple autonomous agents

---

## 3. Operational Problems Being Addressed

| Problem | Current reality | Proposed contribution |
|---|---|---|
| Congested landing pads | Multiple drones returning simultaneously cause delays | TAT-Depot agent sequencing and priority-based pad allocation |
| Battery depletion mid-flight | Fixed schedules do not account for weather or payload | Pre-flight feasibility check; emergency diversion protocol |
| Route inefficiency | Deadhead (empty return) flights waste energy | Triangular milk-run routing where secondary orders exist |
| Weather-adaptive routing | Static routes cannot avoid deteriorating conditions | A* re-weighting with weather cell penalties |
| Assignment suboptimality | Nearest-drone assignment ignores fleet state | ML-predicted cost used to compare candidate assignments |

---

## 4. Current Assumptions and Evidence Gaps

| Assumption | Evidence status |
|---|---|
| Drone battery model (2.8 Wh/km base) | Approximation; not calibrated against physical hardware |
| 65 km/h cruise speed | Typical for multi-rotor delivery drones; not validated for specific models |
| 90-second battery swap time | Assumed; hardware-dependent |
| 50 m minimum horizontal separation | Simulation safety threshold; not a certified aviation standard |
| Open-Meteo weather accuracy | Real API data; not validated as precise enough for drone flight decisions |
| Healthcare use case | Scenario only; no clinical or regulatory validation |

---

## 5. System Boundaries

**In scope:**
- Autonomous dispatch, routing, and landing-pad management (simulation)
- Multi-strategy comparison (baseline, rule-based, ML-assisted)
- Battery and weather constraint enforcement (simulation only)
- Decision transparency logging

**Out of scope:**
- Physical drone control or flight firmware
- Regulatory compliance (CAA Sri Lanka or any aviation authority)
- Real-world GPS, collision avoidance, or fail-safe hardware
- Clinical validation of healthcare delivery outcomes
- Comparison with actual ground transport performance

---

## 6. Supported Scenarios and Operating Conditions

| Scenario | Description |
|---|---|
| Morning peak load | 5 simultaneous orders, 2+ depots, full fleet |
| Triangular milk-run | Chained delivery eliminating deadhead return |
| Medical priority delivery | MEDICAL-priority override, 12-minute SLA |
| Pad congestion | Landing pad blocked; diversion to alternate depot |
| Microburst wind | 60% battery discharge increase; route re-evaluation |
| Drop-zone obstacle | Automated resolution (winch-drop or lockbox reroute) |
| Battery emergency | Drone below 15% triggers emergency depot diversion |

---

## 7. Safety Constraints (Simulation)

1. Drone dispatched only if battery ≥ estimated round-trip cost + 20% reserve.
2. Emergency diversion triggered at battery < 15%.
3. Minimum 50 m horizontal separation monitored and logged.
4. Landing pad not double-booked; pad released on divert.
5. ML model predictions never override hard battery or separation constraints.
6. System falls back deterministically when AI or weather service is unavailable.

**These are simulation constraints only. They do not constitute certified safety systems.**

---

## 8. Measurable Project Objectives

| Objective | Metric | Target (indicative) |
|---|---|---|
| Delivery reliability | Delivery rate (%) | > 80% across benchmark scenarios |
| Energy efficiency | Energy consumed per delivery (% points) | Comparable to or better than baseline |
| Dispatch quality | Mean completion time (s) | AI-assist ≤ SkyGrid ≤ Baseline (hypothesis; results determine truth) |
| Safety | Separation violations per episode | 0 (target; any violations logged) |
| Decision transparency | All decisions logged with reason | 100% |
| Reproducibility | Same seed → same results | Must be verifiable |
| ML accuracy | Validation RMSE for completion_time_s | Reported honestly |

---

## 9. Conditions Explicitly Outside Scope

- Drones operating autonomously without human oversight
- Flight over people, in controlled airspace, or at night (unevaluated)
- Real-time payload tracking or chain-of-custody verification
- Cost comparison with ground ambulance or motorcycle courier services
- Guarantees of SLA adherence in any real operational environment
- Any claim that SkyGrid outperforms baseline without experimental evidence
