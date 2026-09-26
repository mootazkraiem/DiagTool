# clean-2 live path — performance (measured, not optimised)

Production models: clean-2-002 (commit 9029fdd), one 200-tree IsolationForest per CAN ID.
Harness: `python -m backend.ml.validation.benchmark_clean2 --frames N --out report.json`
(the replay_runner loop: one `RealtimeEngine` per selected vehicle, one `process_frame`
per frame, the model scored on every 5th frame of each CAN ID). Recordings are each
family's clean-2 holdout, first N frames.

## Step 12 (2026-09-25), N = 10,000

| Family | Bus frames/s | Processed frames/s | Real-time factor | Model call (mean / p99) |
|---|---|---|---|---|
| jaguar_ipace | 2,990 | 262 | 0.09× | 23.6 / 32.7 ms |
| kia_ev6 | 448 | 224 | 0.50× | 23.5 / 33.8 ms |
| nissan_leaf_2019 | 98 | 205 | 2.10× | 23.8 / 34.6 ms |
| road_ambient | 2,391 | 219 | 0.09× | 23.7 / 34.7 ms |

## Step 11 (2026-09-24), N = 30,000

| Family | Bus frames/s | Processed frames/s | Real-time factor | Model call (mean / p99 / max) | Alerts per bus-second |
|---|---|---|---|---|---|
| road_ambient | 2,393 | 166 | 0.07× | 29.8 / 49.6 / 90.2 ms | 0 |
| kia_ev6 | 406 | 162 | 0.40× | 31.2 / 58.1 / 115.5 ms | 8.3 |
| nissan_leaf_2019 | 108 | 115 | 1.07× | 41.9 / 51.2 / 174.4 ms | 0.78 |

(Step 11 ran alongside a concurrent offline analysis; Step 12 ran alone.)

## Findings

- One per-CAN-ID model call costs about 24–42 ms (200 trees, one row). With scoring on
  every 5th frame per ID, the path sustains roughly **115–260 frames/s**.
- Buses above that rate cannot be scored in real time: road_ambient and jaguar_ipace
  (~2,400–3,000 frames/s) run at **0.07–0.09× real time**, kia_ev6 at 0.4–0.5×.
  nissan_leaf_2019 (~100 frames/s) keeps up.
- Offline `/analyze`: 491,969 frames of nissan_leaf_2019 took 187 s. A 50,361-frame
  Jaguar file took 410 s when a timestamp-unit bug made 34,573 frames anomalous (each
  anomaly is enriched separately); with the fix it takes 16 s. The app allows 420 s for a
  vehicle-model analysis, so a recording with tens of thousands of anomalies can still
  approach the limit.
- Not changed: 200 trees, the every-5th-frame scoring, the models. Optimisation is a
  separate, later step.
