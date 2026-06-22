# CANvisionNative — Full System Roadmap

**Goal:** Live hybrid vehicle CAN bus intrusion detection with multi-state ML, real-time graphs, and an AI-powered CAN Security Analyst Assistant.

---

## Current State Snapshot
_Last updated: 2026-06-21_

| Layer | Status | Note |
|---|---|---|
| Offline replay IDS | ✅ Working | IsolationForest on 7M frames, 18 vehicle models, full DBC decode pipeline |
| Live ML scoring | ✅ Working | Fusion score + 4-layer anomaly detection, mock + hardware paths |
| CAN Security Analyst | ✅ Working | Context-builder with 4 sources; Gemini → Ollama → template |
| Real-time graphs | ✅ Working | Fusion chart, telemetry trends, CAN-ID bars, attack distribution |
| Session recording | ✅ Working | REC/STOP, REC+INJECT, auto-replay after stop |
| DBC decode pipeline | ✅ Working | cantools + vehicle profiles + signal map |
| Offline full pipeline | ✅ Working | MF4/CSV/ASC/candump → DBC decode → ML scoring → results panel |
| Hardware backend | ✅ Wired | can_interface.py, /api/live/hardware/* — untested (no adapter) |
| OBD2 / hardware | ⛔ Blocked | ELM327 adapter not arrived — M2 cannot be validated |

---

## M1 — Fix the Broken Live Foundation ✅ COMPLETE

- [x] Fix `/vehicle` payload mapping bug (MockSignals key mismatch)
- [x] Add `/api/live/start` and `/api/live/stop` endpoints
- [x] Wire `VehicleDataService.Start()` / `Stop()` to backend
- [x] Dashboard sparklines bound to rolling 120-entry fusion score buffer
- [x] Smoke test: mock data → ML scoring → alert fires → dashboard updates

---

## M2 — OBD2 / USB-CAN Hardware Layer ⛔ BLOCKED

> All code is written and wired. Blocked on physical ELM327 USB adapter.

### What's implemented
- [x] `backend/hardware/can_interface.py` — `python-can` wrapper for ELM327 (slcan), PEAK PCAN (pcan), SocketCAN
- [x] `POST /api/live/hardware/connect` — `{interface, channel, bitrate, vehicle_id}` → starts reader thread
- [x] `POST /api/live/hardware/disconnect` — stops reader thread cleanly
- [x] `GET /api/live/hardware/status` — connection state, interface type, live FPS, buffer depth
- [x] Settings UI: interface type selector, COM port, vehicle selector, CONNECT / DISCONNECT buttons
- [x] DBC decode wired into live frame path before `RealtimeEngine.process_frame()`

### What requires the adapter
- [ ] End-to-end connect test (ELM327 → slcan → python-can → server)
- [ ] Validate frame rate matches vehicle CAN bus (500 Kbps typical)
- [ ] Real baseline session: 10–20 min normal drive → capture for retraining

**Done when:** Plug in ELM327 → click CONNECT in Settings → real vehicle frames flow into the IDS pipeline → alerts fire on the live vehicle.

---

## M3 — Multi-State ML Training ✅ COMPLETE

> 7,064,066 frames across 66 sources → 18 vehicle-specific models + 1 general model.

### Training corpus
| Source | Frames | Notes |
|---|---|---|
| `road_ambient` | 1,737,195 | ROAD dataset — U. Michigan, 12 ambient drives |
| `car_hacking_normal` | 1,200,000 | OTIDS Car-Hacking, 4 CSVs (normal rows only) |
| `nissan_leaf` | 1,163,181 | Community EV CAN logs |
| `bmw_i3` | 1,044,993 | Community EV CAN logs |
| `kia_ev6` | 886,368 | Community EV CAN logs |
| + 13 more | ~1,032,329 | Kia Soul, Jaguar I-PACE, MG ZS EV, Tesla, … |

### Parsers implemented
- [x] SavvyCAN CSV (multi-vehicle EV logs)
- [x] candump `can0  ID  [DLC]  bytes`
- [x] candump-ts `(ts) can0 ID#hexdata` (ROAD dataset format)
- [x] Vector ASC `timestamp  ID  Rx  d  DLC  bytes`
- [x] PCAN text `timestamp  HEX_ID  DLC  b0..b7`
- [x] Nissan BusMon UTF-16LE (null-byte strip fix)
- [x] Car-Hacking CSV `timestamp,can_id_hex,dlc,b0..b7,flag` (R=normal)

### Retrain command
```
python -m backend.ml.state_based_pipeline
```

### Still hardware-blocked
- [ ] Fine-tune KMeans thresholds on real hybrid vehicle data
- [ ] Validate false positive rate < 5% on a real normal driving session

---

## M4 — CAN Security Analyst Assistant ✅ COMPLETE

> Replaced classical document-RAG. System is now a domain-specific automotive cybersecurity analyst.

### Architecture

```
User question / alert
        ↓
  Context Builder
        ↓
┌───────────────────────────────────────────┐
│  1. Current anomaly features              │
│     (can_id, state, freq, entropy, score, │
│      layer — parsed from alert + reason)  │
│                                           │
│  2. Normal state statistics               │
│     (state_stats.json: expected freq,     │
│      entropy, inter-arrival per state)    │
│     → deviation labels: "1470 msg/s —     │
│       ABOVE NORMAL (expected 50–120; ×12)"│
│                                           │
│  3. Attack KB match                       │
│     (keyword retrieval, attack_kb.json,   │
│      9 entries: DoS/Fuzzy/RPM/Voltage/…) │
│                                           │
│  4. Historical similar anomalies          │
│     (cosine similarity on normalised      │
│      freq+entropy+score 3-vector;         │
│      JSONL store, grows at runtime)       │
└───────────────────────────────────────────┘
        ↓
  LLM Provider Chain
  Gemini 1.5 Flash → Ollama (llama3/gemma) → Template
        ↓
  Human-readable analysis:
  summary | detail | recommendation
```

### Key files
| File | Role |
|---|---|
| `backend/ml/explainer/context_builder.py` | Assembles 4 context sources + deviation labels |
| `backend/ml/explainer/anomaly_store.py` | JSONL history + feature cosine similarity |
| `backend/ml/explainer/rag.py` | KB keyword lookup (one source among four) |
| `backend/ml/explainer/llm.py` | Provider chain + analyst prompts |
| `backend/knowledge/attack_kb.json` | 9-entry attack taxonomy |
| `backend/knowledge/state_stats.json` | 7 driving states × 4 feature ranges |
| `backend/knowledge/signal_map.json` | DBC signal definitions per CAN-ID |
| `backend/ml/outputs/anomaly_history.jsonl` | Historical anomaly store (auto-populated) |

### Done
- [x] Context builder — 4 sources, deviation tags, state stats
- [x] Anomaly store — JSONL, cosine similarity, threshold 0.5, top-3
- [x] Analyst prompts — comparison to baseline, historical context, KB match
- [x] Provider chain — Gemini (urllib, no package) → Ollama → template
- [x] Auto-persist: `explain_alert()` appends each resolved alert to history
- [x] Chat mode — investigative Q&A: why flagged / normal baseline / similar cases / mitigation
- [x] KB match badge in AnomalyIntelView (amber label, attack taxonomy entry)
- [x] `GET /api/explain/{alert_index}` and `POST /api/chat` wired in server.py

---

## M5 — Real-Time Graphs and Live Visualization ✅ COMPLETE

- [x] Fusion score polyline — rolling 120-entry buffer, threshold lines at 0.35/0.55/0.80
- [x] Per-CAN-ID activity bar chart — top 10 IDs, colour-coded by avg score
- [x] Attack type distribution chart — top 5, horizontal bars
- [x] Vehicle signal trend charts — Speed, SOC%, MotorTemp, Voltage
- [x] Live CAN frame monitor — scrolling table, anomaly score badge

---

## M6 — Session Recording and Replay ✅ COMPLETE

- [x] `backend/hardware/session_recorder.py` — polls live buffer every 100ms, writes timestamped CSV
- [x] `/api/session/record/start`, `/stop`, `/status`, `/list` endpoints
- [x] REC pod in LogPlayback header — REC / STOP buttons, live frame counter, elapsed time
- [x] Auto-trigger `/api/replay/start` after recording stops
- [x] REC+INJECT mode — fires simulator attack mid-session → labelled CSV for M3 retraining

---

## M7 — Full Integration and Final Validation ✅ COMPLETE (pending hardware demo)

- [x] SETUP.md — Python env, pip install, uvicorn start, WPF launch, quick-start guide
- [x] PDF export — `EXPORT PDF` in AnomalyIntelView; `PdfReportBuilder.cs` (PDFsharp); A4 report with header, summary stats, paginated alert table
- [x] CSV export — `EXPORT CSV` in AnomalyIntelView + Diagnostics; columns include `out_of_range`
- [x] Config persist — `AppConfig` loads/saves `%AppData%\CANvision\config.json`; `GOOGLE_API_KEY` applied as env var on startup
- [x] System health panel — `/api/system/health`, Home health rows (ML MODEL / LLM / UPTIME)
- [x] Settings model info — cluster count, LLM provider, model status from backend
- [ ] Full end-to-end hardware demo — _(hardware blocked)_

---

## M8 — Offline + Live Full Decode Pipeline ✅ COMPLETE (pending hardware validation)

### Phase 1 — DBC Decoding Foundation ✅

- [x] `backend/decoding/vehicle_profiles.py` — vehicle registry, DBC file mapping
- [x] `backend/decoding/dbc_manager.py` — cantools loader, `decode(vehicle_id, can_id, bytes) → signals`
- [x] `GET /api/vehicles` — supported vehicle list
- [x] `GET /api/vehicles/{vehicle_id}/can_ids` — CAN-IDs defined in DBC

### Phase 2 — Offline Full Pipeline ✅

- [x] `backend/offline/session_analyzer.py` — detect format → parse → DBC decode → ML score → session JSON
- [x] Parsers: MF4 (asammdf), CSV (Car-Hacking / SavvyCAN), ASC (Vector), candump, PCAN
- [x] `POST /api/offline/analyze` — `{file_path, vehicle_id}` → `session_id`
- [x] `GET /api/offline/status/{session_id}` — progress %
- [x] `GET /api/offline/frames/{session_id}` — paginated frames + signals + anomaly scores
- [x] `GET /api/offline/summary/{session_id}` — alert count, top threats, anomaly rate
- [x] LogPlayback UI — IMPORT CAN LOG button, vehicle selector, offline results panel
- [x] Offline results banner — Total Frames / Anomalies / Rate tiles + Top Suspicious CAN IDs table
- [x] Session metadata sidebar — Vehicle Profile, Duration, Anomaly Rate (orange when anomalies found)

### Phase 3 — Live Hardware Pipeline ✅ (code complete, untested)

- [x] `backend/hardware/can_interface.py` — `python-can` wrapper (ELM327 slcan, PEAK pcan, SocketCAN)
- [x] `POST /api/live/hardware/connect` and `/disconnect` endpoints
- [x] `GET /api/live/hardware/status`
- [x] DBC decode wired into live frame path
- [x] Settings UI — interface selector, COM port, vehicle selector, CONNECT / DISCONNECT
- [ ] Validated on real hardware — _(hardware blocked)_

### Phase 4 — Polish ✅

- [x] Decoded signal display in TelemetryView (named signals with units)
- [x] Session metadata in LogPlayback sidebar
- [x] CSV export with `out_of_range` flag and subsystem column
- [ ] Vehicle auto-detection by CAN-ID fingerprinting _(optional / future)_

---

## Milestone Summary
_Updated 2026-06-21_

```
M1  Fix live foundation           ██████████  100%  ✅ Complete
M2  Hardware / OBD2               ░░░░░░░░░░    0%  ⛔ Blocked — ELM327 adapter not arrived
M3  Multi-state ML (7M frames)    ██████████  100%  ✅ Complete — 18 vehicle models
M4  CAN Security Analyst          ██████████  100%  ✅ Complete — context-builder, 4 sources
M5  Real-time graphs              ██████████  100%  ✅ Complete
M6  Session recording             ██████████  100%  ✅ Complete
M7  Full integration              █████████░   95%  ✅ Software done — hardware demo pending
M8  Offline + live decode         █████████░   90%  ✅ All code done — hardware validation pending
```

### What remains (software)

Nothing. All software tasks are complete.

### What remains (hardware)

When the ELM327 USB adapter arrives:

1. **M2** — Plug in → identify COM port in Device Manager → set in Settings → click CONNECT → confirm live frames in dashboard
2. **M3** — Capture 10–20 min normal drive session → retrain KMeans thresholds → validate FP rate < 5%
3. **M7** — End-to-end demo: connect → drive → see live IDS alerts + AI explanations + real-time graphs
4. **M8 Ph3** — Confirm DBC decode works on real hardware frames

### Execution order (hardware arrives)

`M2 connect test` → `M3 baseline session capture` → `M3 threshold retrain` → `M7 full demo` → `M8 hardware validation`
