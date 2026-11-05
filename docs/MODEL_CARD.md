# SkyGrid Enterprise — ML Model Card

## Model Overview

| Property | Value |
|---|---|
| **Model Name** | SkyGrid Mission-Cost Predictor v1 |
| **Selected Architecture** | GradientBoostingRegressor (scikit-learn) |
| **Wrapper** | MultiOutputRegressor (two joint targets) |
| **Training Framework** | scikit-learn 1.4+ |
| **Trained On** | Simulator-generated synthetic episodes |
| **Last Trained** | 2026-10-30 |

---

## Intended Use

Predict **completion time** (seconds) and **energy consumption** (battery %)
for candidate drone assignments during fleet dispatch decisions.

### Primary Use Case
Rank candidate drone-assignment options within the SkyGrid dispatch agent.
The ML model acts as a fast surrogate for the full simulation physics model,
enabling rapid comparison of multiple assignment options.

### Not Intended For
- Direct autonomous flight control
- Replacement for hard safety constraints (battery reserve, separation)
- Real-world operational planning without physical hardware validation
- Medical decision-making

---

## Training Data

| Property | Value |
|---|---|
| Source | SkyGrid simulation engine (synthetic) |
| Size | 5,000 episodes |
| Split | 3,500 train / 750 validation / 750 test |
| Split Strategy | Temporal by generation seed |
| Generation Seed | 42 |
| Format | CSV |

### Feature Descriptions (12 inputs)

| Feature | Type | Range | Description |
|---|---|---|---|
| `route_dist_km` | float | 0.1 – 12 | Great-circle distance depot→destination |
| `battery_start_pct` | float | 35 – 100 | Drone battery at dispatch |
| `battery_soh_pct` | float | 75 – 100 | Battery state-of-health |
| `payload_kg` | float | 0.5 – 8.0 | Package weight |
| `drone_speed_kmh` | float | 50 – 75 | Drone cruise speed |
| `wind_speed_kmh` | float | 0 – 55 | Estimated wind speed |
| `weather_severity` | int | 0 – 3 | 0=clear, 1=caution, 2=advisory, 3=unsafe |
| `num_active_drones` | int | 0 – 5 | Other airborne drones at dispatch |
| `pad_queue_estimate` | int | 0 – 2 | Busy pads at origin depot |
| `priority_ordinal` | int | 0 – 3 | 0=standard … 3=medical |
| `motor_hours` | float | 50 – 850 | Drone age proxy |
| `alt_segment_ratio` | float | 0.5 – 0.7 | Fraction of route at cruise altitude |

### Label Descriptions (2 outputs)

| Label | Type | Description |
|---|---|---|
| `completion_time_s` | float | Simulated mission duration (dispatch → swap start) |
| `energy_consumed_pct` | float | Total battery consumed over full mission |

---

## Model Comparison

| Model | Time RMSE (val) | Energy RMSE (val) | Time R² (test) | Energy R² (test) | Train Time |
|---|---|---|---|---|---|
| Ridge Regression | 30.73 s | 3.67 % | 0.9839 | 0.9263 | 0.01 s |
| **Gradient Boosting** | **9.48 s** | **0.81 %** | **0.9987** | **0.9968** | **4.2 s** |

Selection criterion: lowest validation RMSE (averaged across both targets).

---

## Performance Metrics (Held-out Test Set, n=750)

| Metric | completion_time_s | energy_consumed_pct |
|---|---|---|
| MAE | 7.05 s | 0.56 % |
| RMSE | 9.51 s | 0.78 % |
| R² | 0.9987 | 0.9968 |

---

## Key Feature Importances (Gradient Boosting)

Feature importances are measured by the total reduction in loss
contributed by each feature during tree construction.

Top features (ranked by importance for completion_time_s):
1. `route_dist_km` — dominant driver of mission time
2. `drone_speed_kmh` — directly affects travel duration
3. `battery_soh_pct` — affects effective speed
4. `pad_queue_estimate` — adds waiting time
5. `wind_speed_kmh` — affects energy and therefore re-routing

(Full importance values saved in `results/ml_feature_importance.json`)

---

## Safety Constraints

The ML model **does not override** any hard safety constraint:

| Constraint | Enforced By | ML Can Override? |
|---|---|---|
| Battery reserve ≥ 20% on arrival | Dispatcher + Predictor | **No** |
| Emergency diversion at < 15% | Simulation engine | **No** |
| Minimum 50 m separation | Simulation engine | **No** |
| Payload < drone max capacity | Dispatcher | **No** |
| Model prediction sanity check | Predictor fallback | **No** |

If the model produces implausible predictions (negative time, >100% energy,
time > 7200 s), the predictor automatically falls back to deterministic
computation using the same physics formula as the simulation engine.

---

## Limitations and Risks

1. **Synthetic data only.** The model has never seen real-world flight data.
   R² scores reflect how well it approximates the simulator, not reality.

2. **Circular evaluation risk.** Since training data comes from the same
   simulator used for benchmarks, high R² may reflect model simplicity
   rather than generalisation.

3. **Narrow feature distribution.** Training covers the Colombo area grid
   (~8.8 km). Performance outside this region is untested.

4. **No temporal dynamics.** The model does not capture time-series effects
   (battery degradation over consecutive missions, traffic patterns).

5. **No adversarial robustness.** Input validation checks for range but
   not for adversarial inputs.

---

## Ethical Considerations

- The model must not be used for autonomous medical logistics without
  independent clinical validation and regulatory approval.
- Battery and safety predictions are approximate; real-world drone
  operations require certified safety systems.
- See `docs/ETHICS_AND_RESPONSIBLE_AI.md` for the full responsible AI statement.

---

## Reproducibility

```bash
# Generate data
python backend/ml/data_generation.py --samples 5000 --seed 42

# Prepare dataset
python backend/ml/dataset.py

# Train model
python backend/ml/train.py --seed 42

# Results saved to results/ml_metrics.json
```

All random seeds are fixed. The same commands should produce identical
models and metrics on the same Python/scikit-learn version.
