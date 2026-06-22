# CANvisionNative — Setup Guide

> CAN Bus Intrusion Detection System with real-time ML scoring and AI-powered anomaly explanation.

---

## Requirements

| Component | Version | Notes |
|---|---|---|
| Windows | 10 or 11 | 64-bit |
| .NET Runtime | 4.8 | Usually pre-installed on Windows 10/11 |
| Python | 3.11 – 3.14 | Install from python.org |
| Git | Any | For cloning |
| ELM327 USB adapter | — | **Required for live vehicle data (M2). Not needed for replay mode.** |

---

## 1. Clone and Prepare

```
git clone <repo-url>
cd can_project
```

---

## 2. Python Backend Setup

### 2a. Create a virtual environment

```
python -m venv .venv
.venv\Scripts\activate
```

### 2b. Install dependencies

```
pip install -r requirements.txt
```

Core packages installed:
- `fastapi`, `uvicorn` — API server
- `scikit-learn`, `joblib` — IsolationForest + KMeans ML pipeline
- `pandas`, `numpy` — feature engineering
- `asammdf`, `cantools`, `python-can` — CAN log parsing (MF4, DBC, native CAN)
- Gemini LLM is accessed via raw `urllib` — no extra package required

### 2c. (Optional) Ollama for local LLM

If you don't have a Google API key, install [Ollama](https://ollama.com/download) and pull a model:

```
ollama pull gemma2:2b
```

The backend will automatically use Ollama as a fallback if Gemini is not configured.

### 2d. (Optional) Set Google Gemini API Key

**Option A — via the app UI:**
1. Open CANvisionNative → Settings
2. Enter your key in the **GOOGLE API KEY (GEMINI)** field
3. Click **SAVE SETTINGS**

The key is stored in `%AppData%\CANvision\config.json` and applied on next launch.

**Option B — environment variable:**
```
set GOOGLE_API_KEY=your-key-here
```

Get a free key at [aistudio.google.com](https://aistudio.google.com).

---

## 3. Start the Backend

From the project root (with `.venv` active):

```
python -m uvicorn backend.api.server:app --host 127.0.0.1 --port 8765
```

Confirm it's running:
```
curl http://127.0.0.1:8765/health
```
Expected: `{"status":"ok","service":"CANvision IDS Backend",...}`

> **Tip:** The WPF app auto-starts the backend on launch if it detects Python at the default path (`C:\Users\<you>\AppData\Local\Programs\Python\Python313\python.exe`). You can also start it manually before launching the app.

---

## 4. Launch the WPF App

Open `CANvisionNative.sln` in Visual Studio 2022 (or run the built `.exe`):

```
bin\Debug\net48\CANvisionNative.exe
```

The app starts at the **Home** screen. Backend status (CONNECTED / OFFLINE) is shown in the top-right corner.

---

## 5. Run a Replay Analysis (No Hardware Required)

1. Click **IMPORT CAN LOG** on the Home screen
2. Select one of the packaged datasets from `assets/archive/`:
   - `DoS_dataset.csv` — DoS flood attack
   - `Fuzzy_dataset.csv` — Fuzzy injection
   - `RPM_dataset.csv` — RPM spoofing
   - `gear_dataset.csv` — Gear injection
   - `normal_run_data.txt` — Baseline (no attacks)
3. Analysis runs automatically (~10–30 seconds depending on file size)
4. Navigate to **Anomaly Intel** to review detected events and AI explanations
5. Navigate to **Log Playback** for forensic timeline review

---

## 6. Live Attack Simulation (No Hardware Required)

To test the full pipeline without a real vehicle:

1. Go to **Log Playback**
2. Click **REC+INJECT** in the header bar
   - This starts recording live CAN frames AND launches the attack simulator
3. Wait 30–60 seconds to capture attack patterns
4. Click **STOP** — recording stops, replay analysis runs automatically
5. Review results in **Anomaly Intel**

Alternatively, from **Settings → LAUNCH ATTACK TEST** to start the simulator directly.

---

## 7. Hardware Setup — ELM327 / USB-CAN (M2 — Requires Adapter)

> **This section requires an ELM327 USB adapter or a USB-CAN adapter.**

### 7a. Install drivers

- **ELM327 USB:** Install the CH340 or CP2102 USB serial driver (included with most adapters, or download from the manufacturer)
- **USB-CAN (e.g., PEAK PCAN-USB):** Install the PEAK drivers from peak-system.com

### 7b. Identify COM port

1. Plug in the adapter
2. Open Device Manager → Ports (COM & LPT)
3. Note the port number (e.g., `COM5`)

### 7c. Configure in the app

Go to **Settings → HARDWARE INTERFACE** and set:
- **OBD2 ADAPTER:** `ELM327 USB` (or `USB-CAN`)
- **COM PORT:** `COM5` (your port)
- **BAUD RATE:** `500000` (CAN default) or `38400` (ELM327 default)

> Hardware connect endpoint (`POST /api/hardware/connect`) is part of M2 and is not yet implemented in this build. Once M2 ships, clicking Connect will start live OBD2 frame capture.

---

## 8. ML Model Info

The IDS uses:
- **IsolationForest** — unsupervised anomaly scoring (per-frame)
- **KMeans** — vehicle state clustering (parking / idle / driving / regen)
- **4-layer fusion** — Timing · Payload · ML · Temporal scores combined

Pre-trained models live in `assets/models/` — 18 vehicle-specific folders:

| Folder | Source |
|---|---|
| `general/` | General-purpose baseline |
| `kaggle_normal/` | OTIDS Kia Soul normal traffic |
| `nissan_leaf/`, `nissan_leaf_2019/` | Nissan EV open logs |
| `bmw_i3/`, `kia_ev6/`, `kia_soul/` | OBD2 EV capture logs |
| `tesla/`, `jaguar_ipace/`, `mg_zs_ev/` | EV CAN logs |
| `road_ambient/` | ROAD dataset — 12 ambient drives (U. Michigan) |
| `car_hacking_normal/` | OTIDS Car-Hacking dataset — normal-only rows |
| + 6 more | `hyundai_ioniq5`, `skoda_enyaq`, `geely_sea_platform`, … |

Total training corpus: **7 million frames** across **66 sources**.

Model status and cluster count are shown in **Settings → NEURAL CORE CONFIG** and on the **Home** screen.

---

## 9. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Home shows BACKEND OFFLINE | Python server not running | Start uvicorn (Section 3) |
| No alerts after replay | Model not loaded | Check `backend/ml/models/` contains `.joblib` files |
| LLM shows `--` | No Gemini key, no Ollama | Set `GOOGLE_API_KEY` or install Ollama |
| Gemini returns error | Invalid or expired key | Re-enter key in Settings |
| App hangs at startup | Backend auto-start path mismatch | Start uvicorn manually before launching app |
| Recording produces 0 frames | Live simulator not running | Use REC+INJECT instead of REC alone |

---

## 10. Project Structure

```
can_project/
├── backend/
│   ├── api/server.py             # FastAPI entrypoint — all endpoints
│   ├── data_processing/          # CAN log parser, feature engineering
│   ├── hardware/
│   │   └── session_recorder.py   # Live session capture (M2)
│   ├── knowledge/
│   │   └── attack_kb.json        # RAG knowledge base (9 attack entries)
│   └── ml/
│       ├── core/                 # Feature engineering, realtime engine
│       ├── explainer/            # RAG retrieval + Gemini/Ollama LLM chain
│       ├── outputs/              # Alerts, validation reports, sessions
│       └── state_based_pipeline.py  # Training script
├── assets/
│   ├── archive/                  # Car-Hacking (OTIDS) datasets
│   ├── models/                   # Trained .joblib files (18 vehicle folders)
│   └── road/                     # ROAD dataset (U. Michigan ambient logs)
├── Models/                       # C# data models + AppConfig
├── Services/                     # VehicleDataService, PythonApiClient, PDF builder
├── UI/                           # WPF XAML views
├── ViewModels/                   # MVVM ViewModels (SectionViewModels.cs)
└── ROADMAP.md                    # Milestone tracker
```

---

*CANvisionNative — Hybrid Vehicle CAN Bus IDS*
