# CANvisionNative — Session Notes (2026-06-11)

## What was built this session

### 1. AI Anomaly Intelligence (module 08) — COMPLETE
Full split-panel view for IDS alert inspection + GPT-4o-mini explanations.

**Layout** (matches all other views exactly):
- Top row: 6 KPI cards (Total Alerts / Critical / High-Warning / Top CAN ID / Score / AI Engine)
- Left panel (310px): Scrollable alert list with severity color, CAN ID, score, timestamp
- Center panel (*): Selected alert header + 4-layer attribution bars (Timing / Payload / ML / Temporal)
- Right panel (330px): AI explanation card — Summary / Analysis / Recommendation
- Action bar: Explain / Refresh / Export buttons
- Status bar: 26px standard footer

**How to get AI explanations:**
```powershell
$env:OPENAI_API_KEY = "sk-your-key-here"
python -m uvicorn backend.api.server:app --host 127.0.0.1 --port 8765
```
Without the key, it falls back to a template-based explanation automatically.

**New endpoint:** `GET /api/explain/{alert_index}` (0 = most recent alert)

### 2. LLMExplainer upgraded (backend/ml/engine.py)
- Real `openai.chat.completions.create()` call to GPT-4o-mini
- Auto-detects `OPENAI_API_KEY` env var
- Graceful fallback to enhanced template if key not set
- Separate `explain_alert()` method for live IDS alerts

### 3. Telemetry Signal Channels — COMPLETE
Replaced static LIVE BUS TIMELINE with a live **SIGNAL CHANNELS** section showing 4 rolling charts:
- SPEED (green #56F0AC)
- SOC % (cyan #00C8C8)
- MOTOR TEMP (orange #FF8C3A)
- VOLTAGE (purple #96B4FF)

**What changed:**
- `ViewModels/SectionViewModels.cs` — added `socHistory` buffer + 4 `*ChannelPoints` PointCollection properties + `OnPropertyChanged` notifications
- `UI/TelemetryView.xaml` — replaced LIVE BUS TIMELINE block with SIGNAL CHANNELS (4-row Grid, each row = label+value+rolling chart)
- Each chart: Canvas 400×34 inside Viewbox (Stretch=Fill), live-updating every 500ms via DataUpdated event

---

## Current view status

| View | Status | Notes |
|------|--------|-------|
| Home / Garage | ✅ Complete | Import + live session start |
| Dashboard | ✅ Complete | Live score chart, KPIs, CAN monitor |
| Telemetry | ✅ Complete | KPI sparklines + 4-channel signal charts |
| Diagnostics | ✅ Complete | IDS event list, filter, scan |
| Log Playback | ✅ Complete | Full forensic timeline |
| Analytics | ⚠️ Partial | Charts work; NeuralConfidence/HeatIndex still fake |
| Validation Lab | ✅ Complete | Precision/Recall/F1 evaluation |
| Anomaly Intel | ✅ Complete | Alert list + LLM explanation layer |
| Settings | ✅ Complete | Config display |

---

## Next steps (priority order)

### 1. Analytics real stats [NEXT]
**Problem:** `NeuralConfidence`, `HeatIndex`, `ReliabilityScore` are fake/hardcoded.
**Fix:** Derive from `VehicleDataService.AlertHistory` — same data Dashboard uses, just aggregated differently.
- `NeuralConfidence` → detection confidence from `VehicleDataService.DetectionConfidence`
- `HeatIndex` → alert rate per minute from `AlertHistory`
- `ReliabilityScore` → ratio of high-confidence alerts vs total

### 2. M1 Smoke Test
Run app + backend, import a replay CSV, confirm:
- Anomaly score chart spikes on attack frames
- Alerts appear in Anomaly Intel view
- AI explanation returns something when you click "Explain with AI"
- Telemetry channels update and draw rolling lines

### 3. M2 OBD2 [BLOCKED — needs ELM327 hardware]

---

## Key architecture facts

```
Fusion score range:  0.0 – 1.5  (NOT 0–100)
Thresholds:          0.35 elevated | 0.55 alert | 0.80 critical
Layer weights:       timing(0.35) + payload(0.35) + ml(0.20) + persistence(0.10)
Backend port:        8765
Python path:         C:/Users/benkr/AppData/Local/Programs/Python/Python313/python.exe
Start backend:       python -m uvicorn backend.api.server:app --host 127.0.0.1 --port 8765
All ViewModels:      ViewModels/SectionViewModels.cs  (single file, do NOT split)
Section enum:        Models/SectionKey.cs
Section descriptors: Models/SectionCatalog.cs
View templates:      UI/Theme/ViewTemplates.xaml
DI wiring:           App.xaml.cs
```

## Design language (copy-paste for new views)

```xml
<!-- View root -->
Background="#060E0E"

<!-- Card -->
Background: LinearGradientBrush #0F1A1A → #0A1212
BorderBrush="#28009999" BorderThickness="1" CornerRadius="3" Padding="10,8"

<!-- Active card -->
BorderBrush="#4400C8C8"

<!-- InnerCard -->
Background="#08000000" BorderBrush="#182F36" BorderThickness="1" Padding="9,8"

<!-- Text styles -->
Lbl:   Bahnschrift 8.5  #3A6060  SemiBold
Title: Bahnschrift 12   #00C8C8  SemiBold
Meta:  Bahnschrift 8    #2A4A4A
Mono:  Consolas   10    #D0ECEC

<!-- Colors -->
Accent:   #00C8C8    Good:     #56F0AC
Warning:  #FF8C3A   Critical: #FF5050
Purple:   #B46CFF   Orange:   #FF8C3A

<!-- Row structure (all main views) -->
Row 0:  96px  → UniformGrid Columns="6" KPI strip
Row 1:  *     → 3-column main content (310 | * | 330)
Row 2:  72px  → Action button bar
Row 3:  26px  → Status bar

<!-- RadialGradientBrush bg overlay (all views) -->
#08001818 → #00000000  (GradientOrigin/Center 0.5,0.42  RadiusX=0.58 RadiusY=0.55)

<!-- Action bar background -->
LinearGradientBrush #0C1616 → #080E0E

<!-- Signal channel chart row pattern -->
Grid with ColumnDefinitions 76/* :
  - StackPanel (label Lbl + value Bahnschrift 13 Bold colored)
  - Border (Background=#05001818 BorderBrush=#0C3A6060) > Viewbox Stretch=Fill > Canvas 400×34 > Polyline
Colors: Speed=#56F0AC  SOC=#00C8C8  MotorTemp=#FF8C3A  Voltage=#96B4FF
```

---

## File locations

```
Project root:    C:\Users\benkr\OneDrive\can_project\
Backend:         backend\api\server.py
ML engine:       backend\ml\engine.py
ViewModels:      ViewModels\SectionViewModels.cs
Views:           UI\*.xaml
Converters:      Converters\NumericConverters.cs
Theme:           UI\Theme\ThemeResources.xaml
View templates:  UI\Theme\ViewTemplates.xaml
This file:       SESSION_NOTES.md  (project root)
```
