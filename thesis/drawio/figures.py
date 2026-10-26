"""The diagrams of the report, drawn as draw.io files.

    python figures.py            build and export every figure
    python figures.py usecase    build and export the named figures only

Each .drawio file opens in draw.io; the PNG next to it is the exported figure,
also copied into ../diagrams where the report reads it.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

from dio import (AGGREGATE, ASSOC, COMPOSE, DASHED_OPEN, DEPEND, FLOW, GENERALIZE, Diagram,
                 Sequence, class_height, export)

HERE = Path(__file__).resolve().parent
OUT = HERE.parent / "diagrams"
FIGURES = {}


def figure(fn):
    FIGURES[fn.__name__] = fn
    return fn


def flow(d, a, b, label="", **kw):
    return d.edge(a, b, label, FLOW, **kw)


def chain(d, *ids):
    for a, b in zip(ids, ids[1:]):
        flow(d, a, b)


L, R, T, B = (0, 0.5), (1, 0.5), (0.5, 0), (0.5, 1)


# ── Chapter 1 ───────────────────────────────────────────────────────────────

@figure
def scrum_workflow():
    d = Diagram("scrum_workflow")
    pb = d.box("Product backlog\n(prioritised work)", 80, 50, 140, 50, "yellow")
    sp = d.box("Sprint planning", 250, 50, 140, 40)
    sb = d.box("Sprint backlog", 420, 50, 140, 40, "yellow")
    sprint = d.box("Sprint\n(one to four weeks,\ndaily follow up)", 600, 50, 150, 60)
    inc = d.box("Working increment", 600, 170, 150, 40, "green")
    review = d.box("Sprint review\n(backlog updated)", 420, 170, 140, 50)
    retro = d.box("Retrospective", 250, 170, 140, 40)
    chain(d, pb, sp, sb, sprint, inc, review, retro)
    flow(d, retro, sp, "next sprint")
    return d


@figure
def project_timeline():
    """The Unified Process applied to the project: four phases, the iterations of the
    construction phase, and what each one delivered."""
    d = Diagram("project_timeline")
    W, G, Y = 128, 18, 130
    steps = [
        ("Vision, existing tools,\nuse cases, initial\nrisks and plan", "Feb 2026"),
        ("Executable\narchitecture: client,\nbackend, engine (M1)", "Feb to Mar"),
        ("Iteration 1\nfirst detection pipeline\nand client (M3 to M8)", "Mar to Jun"),
        ("Iteration 2\nvalidation on the Kia\nEV6, six corrections", "Jun to Jul"),
        ("Iteration 3\nhardware layer and\nbench rig (M2)", "Aug to Sep"),
        ("Iteration 4\nmodel rebuild and\nholdout evaluation", "Sep"),
        ("Final release, tests,\ndeployment guide\nand report", "Sep to Oct"),
    ]
    x = lambda i: 20 + W / 2 + i * (W + G)
    phases = [("Inception", 0, 0, "yellow"), ("Elaboration", 1, 1, "purple"),
              ("Construction", 2, 5, "blue"), ("Transition", 6, 6, "green")]
    for name, a, b, color in phases:
        x0, x1 = x(a) - W / 2, x(b) + W / 2
        d.box(name, (x0 + x1) / 2, 40, x1 - x0, 34, color, rounded=False, extra="fontStyle=1;")
    ids = []
    for i, (label, when) in enumerate(steps):
        color = [p[3] for p in phases if p[1] <= i <= p[2]][0]
        ids.append(d.box(label, x(i), Y, W, 74, color))
        d.text(when, x(i) - W / 2, Y + 42, W, 22, align="center", extra="fontColor=#555555;")
    chain(d, *ids)
    return d


# ── Chapter 2 ───────────────────────────────────────────────────────────────

@figure
def usecase():
    """Global use case diagram. The backend is part of the system, not an actor; the
    actors are the analyst, the vehicle or CAN bus and the LLM provider."""
    d = Diagram("usecase")
    d.frame("CANvisionNative", 150, 20, 560, 640)
    analyst = d.actor("Analyst", 60, 340)
    left = [("Import log", 70), ("Select vehicle", 128), ("Describe capture", 186),
            ("Replay log", 244), ("Start live simulation", 302), ("Connect hardware", 360),
            ("Record session", 418), ("Review alerts", 476), ("Export report", 534),
            ("Configure settings", 592)]
    uc = {name: d.usecase(name, 300, y, 170, 44) for name, y in left}
    status = d.usecase("Check model status", 585, 128, 170, 48, color="green")
    detect = d.usecase("Detect anomaly", 585, 302, 160, 50, color="green")
    explain = d.usecase("Request explanation", 585, 476, 170, 50, color="green")
    for name in uc:
        d.edge(analyst, uc[name], "", ASSOC, entry=L)
    d.edge(uc["Select vehicle"], status, "«include»", DASHED_OPEN)
    for name in ("Replay log", "Start live simulation", "Connect hardware"):
        d.edge(uc[name], detect, "«include»", DASHED_OPEN)
    d.edge(explain, uc["Review alerts"], "«extend»", DASHED_OPEN)
    llm = d.actor("LLM provider\n(Gemini, Ollama)", 800, 476)
    bus = d.actor("Vehicle or\nCAN bus", 800, 330)
    d.edge(explain, llm, "", ASSOC)
    d.edge(uc["Connect hardware"], bus, "", ASSOC, exit=R, entry=L, points=[(470, 360), (470, 345)])
    return d


@figure
def activity_replay():
    d = Diagram("activity_replay")
    # the two branches sit right under the left and right corners of the decision (610 +/- 75)
    A, C, B1, B2 = 100, 320, 535, 685
    d.lane("Analyst", 0, 0, 200, 740, "blue")
    d.lane("Desktop client (System)", 200, 0, 240, 740, "green")
    d.lane("Backend (System)", 440, 0, 340, 740, "orange")
    s = d.start(A, 55)
    choose = d.box("Choose a log file", A, 110, 150, 40)
    parse = d.box("Recognise the format\nand read the frames", C, 165, 170, 50, "green")
    vehicle = d.box("Choose the vehicle\nmodel", A, 225, 150, 50)
    run = d.box("Run the analysis", A, 295, 150, 40)
    post = d.box("POST /analyze\n(file, model_id)", C, 355, 170, 50, "green")
    allowed = d.decision("Model allowed\noffline?", 610, 420, 150, 64)
    refuse = d.box("Refuse the analysis\nwith the reason", B1, 495, 140, 50, "orange")
    score = d.box("Score every frame with\nthe model of its identifier", B2, 495, 150, 56, "orange")
    count = d.box("Count the unresolved\nframes and their reasons", B2, 570, 150, 56, "orange")
    checks = d.box("Additional checks,\nmerge bursts into alerts", B2, 645, 150, 56, "orange")
    show_reason = d.box("Show the reason", C, 495, 150, 40, "green")
    stop1 = d.end(C, 555)
    results = d.box("Show the results\non the Dashboard", C, 645, 170, 50, "green")
    replay = d.box("Replay the log\nin Log Playback", A, 645, 150, 50)
    stop2 = d.end(A, 710)
    chain(d, s, choose, parse, vehicle, run, post, allowed)
    chain(d, score, count, checks)
    chain(d, refuse, show_reason, stop1)
    chain(d, results, replay, stop2)
    flow(d, allowed, refuse, "no", exit=L, entry=T)
    flow(d, allowed, score, "yes", exit=R, entry=T)
    flow(d, checks, results)
    return d


@figure
def sequence_explain():
    d = Diagram("sequence_explain")
    s = Sequence(d, numbered=True)
    s.participant("an", "Analyst", 30, actor=True)
    s.participant("vm", "AnomalyIntelViewModel", 150, color="green", stereo="boundary")
    s.participant("cl", "PythonApiClient", 300, color="green", stereo="control")
    s.participant("sv", "server.py", 430, color="orange", stereo="control")
    s.participant("ca", "explanation cache", 545, color="orange", stereo="entity")
    s.participant("ex", "explainer.llm", 660, color="orange", stereo="control")
    s.participant("ge", "Gemini", 780, actor=True)
    s.participant("ol", "Ollama", 870, actor=True)
    s.activate("sv", 185, 785)
    s.activate("ex", 375, 720)
    s.draw_lifelines(885)
    s.draw_activations()
    s.fragment("opt", "explanation not in the cache", 390, 325, 925, 755)
    s.fragment("alt", "Gemini answers", 615, 440, 915, 700, [(520, "Gemini not available")])
    s.fragment("alt", "Ollama answers", 630, 552, 905, 690, [(630, "no model available")])
    s.msg("an", "vm", 128, "select alert")
    s.msg("vm", "cl", 158, "GetAlertExplanationAsync(index)")
    s.msg("cl", "sv", 185, "GET /api/explain/{index}")
    s.self_msg("sv", 210, "find the alert of\nthe current session")
    s.msg("sv", "ca", 275, "get(cache_key)")
    s.msg("ca", "sv", 305, "explanation or none", reply=True)
    s.msg("sv", "ex", 375, "explain_alert(alert)")
    s.self_msg("ex", 395, "build the context\nof the alert")
    s.msg("ex", "ge", 482, "prompt")
    s.msg("ge", "ex", 508, "explanation", reply=True)
    s.msg("ex", "ol", 592, "prompt")
    s.msg("ol", "ex", 618, "explanation", reply=True)
    s.self_msg("ex", 655, "rule based template", 20)
    s.msg("ex", "sv", 715, "explanation + mode", reply=True)
    s.msg("sv", "ca", 740, "store(cache_key, explanation)")
    s.msg("sv", "cl", 780, "JSON", reply=True)
    s.msg("cl", "vm", 810, "ExplainAlertResponse", reply=True)
    s.msg("vm", "an", 860, "explanation,\nengine name", reply=True)
    return d


# ── Chapter 3 ───────────────────────────────────────────────────────────────

@figure
def architecture_overall():
    d = Diagram("architecture_overall")
    d.group("Desktop client (C#, WPF, .NET Framework 4.8)", 170, 10, 360, 290, "blue")
    views = d.box("Views (XAML)", 350, 75, 160, 36)
    vms = d.box("ViewModels", 350, 145, 160, 36)
    services = d.box("Services\nPythonApiClient, VehicleDataService,\nModelSelectionService, CanLogImportService",
                     350, 235, 300, 64)
    d.group("Backend (Python, FastAPI, 127.0.0.1:8765)", 10, 340, 700, 360, "orange")
    api = d.box("REST API\nserver.py", 360, 405, 140, 44, "orange")
    detect = d.box("Detection\nRealtimeEngine,\nvehicle_scoring,\nsession_analyzer", 100, 510, 150, 76, "orange")
    decode = d.box("Decoding\ndbc_manager,\nsignal_discovery", 280, 510, 140, 60, "orange")
    explain = d.box("Explanation\nexplainer/llm.py", 450, 510, 140, 44, "orange")
    store = d.box("Persistence\nSQLite store", 620, 510, 120, 44, "orange")
    models = d.box("Model management\nmodel_manifest,\nmodel_status", 100, 640, 150, 60, "orange")
    hw = d.box("Hardware\ncan_interface", 280, 640, 140, 44, "orange")
    files = d.cylinder("assets/models\n(manifest.json,\nmodels.joblib)", 100, 790, 130, 80)
    gemini = d.cloud("Gemini API", 450, 790, 140, 70, "purple")
    ollama = d.cube("Ollama\n(local model)", 620, 790, 130, 60, "purple")
    flow(d, views, vms, "data binding")
    flow(d, vms, services)
    flow(d, services, api, "HTTP + JSON")
    for target in (detect, decode, explain, store):
        flow(d, api, target, exit=B, entry=T)
    flow(d, hw, detect, "frames", exit=L, entry=(1, 0.8))
    flow(d, detect, models)
    flow(d, models, files)
    flow(d, explain, gemini, "HTTPS")
    flow(d, explain, ollama, "HTTP", exit=(0.8, 1), entry=T)
    return d


@figure
def architecture_frontend():
    d = Diagram("architecture_frontend")
    xs = [85, 235, 385, 535, 685]
    screens = ["Home", "Dashboard", "Telemetry", "LogPlayback", "AnomalyIntel"]
    d.group("Views (XAML)", 0, 0, 770, 90, "blue")
    d.group("ViewModels", 0, 150, 770, 240, "green")
    d.group("Services", 0, 440, 770, 170, "orange")
    views = [d.box(f"{s}View", x, 58, 140, 34, "blue", rounded=False) for s, x in zip(screens, xs)]
    vms = [d.box(f"{s}ViewModel", x, 208, 145, 34, "green", rounded=False) for s, x in zip(screens, xs)]
    section = d.uml_class("SectionViewModel", 280, 280, 210,
                          ["#Snapshot : VehicleSnapshot", "#ShowsCapture : bool"],
                          ["#OnDataUpdated(snapshot)"], "green", italic=True)
    data = d.uml_class("VehicleDataService", 15, 485, 190,
                       ["+AlertHistory", "+LoadedReplayPackets", "+DataUpdated : event", "+ReplayLoaded : event"],
                       color="orange")
    client = d.uml_class("PythonApiClient", 300, 480, 210, [],
                         ["+AnalyzeLogsAsync()", "+StartReplayAsync()", "+GetAlertExplanationAsync()",
                          "+DiscoverSignalsAsync()", "+DescribeDatasetAsync()"], "orange")
    select = d.uml_class("ModelSelectionService", 555, 485, 200,
                         ["+SelectedModel", "+SelectionChanged : event"], color="orange")
    for v, m in zip(views, vms):
        flow(d, v, m, "binds")
    for m in vms:
        d.edge(m, section, "", GENERALIZE, exit=B, entry=T)
    flow(d, section, data, "subscribes to events", exit=(0, 0.8), entry=T)
    flow(d, data, client, "polls\nevery 500 ms", exit=R, entry=L)
    flow(d, section, select, "", exit=(1, 0.8), entry=T)
    return d


@figure
def rest_api_flow():
    d = Diagram("rest_api_flow")
    client = d.box("Desktop client\nPythonApiClient", 80, 300, 140, 60, "blue")
    d.group("REST API (server.py)", 180, 20, 250, 540, "green")
    d.group("Backend components", 470, 20, 250, 540, "orange")
    rows = [("/analyze\n/api/offline/*", "Offline analysis\nvehicle_scoring, session_analyzer", 85),
            ("/api/replay/*", "Replay process\nreplay_runner", 150),
            ("/api/live/*\n/api/live/hardware/*", "Hardware\ncan_interface", 285),
            ("/api/explain/{index}\n/api/chat", "Explanation\nexplainer/llm.py", 350),
            ("/api/models\n/api/vehicles", "Model status\nmodel_status, vehicle_profiles", 415),
            ("/api/signals/discover\n/api/dataset/describe", "Capture description\nsignal_discovery, dataset_facts", 480),
            ]
    comps = {}
    for endpoint, comp, y in rows:
        e = d.box(endpoint, 305, y, 200, 48, "green")
        c = d.box(comp, 595, y, 210, 48, "orange")
        comps[comp.split("\n")[0]] = c
        flow(d, client, e, exit=R, entry=L)
        flow(d, e, c)
    edata = d.box("/api/session/*, /api/settings\n/api/db/stats", 305, 535, 200, 40, "green")
    cdata = d.box("SQLite store and settings", 595, 535, 210, 40, "orange")
    flow(d, client, edata, exit=R, entry=L)
    flow(d, edata, cdata)
    engine = d.box("RealtimeEngine", 595, 217, 210, 36, "orange")
    flow(d, comps["Replay process"], engine)
    flow(d, comps["Hardware"], engine)
    return d


@figure
def sequence_replay():
    d = Diagram("sequence_replay")
    s = Sequence(d, numbered=True)
    s.participant("an", "Analyst", 30, actor=True)
    s.participant("vm", "LogPlaybackViewModel", 150, color="green", stereo="boundary")
    s.participant("da", "VehicleDataService", 300, color="green", stereo="control")
    s.participant("sv", "server.py", 440, color="orange", stereo="control")
    s.participant("ru", "replay_runner (subprocess)", 590, color="orange", stereo="control")
    s.participant("en", "RealtimeEngine", 730, color="orange", stereo="control")
    s.participant("rf", "replay result files", 860, color="orange", stereo="entity")
    s.activate("sv", 285, 875)
    s.activate("ru", 320, 735)
    s.draw_lifelines(965)
    s.draw_activations()
    s.fragment("loop", "every frame of the file", 545, 370, 915, 515)
    s.fragment("opt", "every 1,000 frames", 560, 460, 905, 507)
    s.fragment("loop", "every 500 ms until the end", 240, 530, 915, 682)
    s.fragment("opt", "every 10th poll (about 5 s)", 253, 588, 905, 672)
    s.msg("an", "vm", 130, "open file, vehicle selected")
    s.self_msg("vm", 155, "parse the file\n(CanLogImportService)")
    s.msg("vm", "da", 210, "LoadReplayPackets()")
    s.msg("vm", "da", 245, "TriggerBackendReplayAsync()")
    s.msg("da", "sv", 285, "POST /api/replay/start\n{input_path, vehicle_id}")
    s.msg("sv", "ru", 320, "start process", asyn=True)
    s.msg("sv", "da", 350, "state: running", reply=True)
    s.msg("ru", "en", 410, "process_frame(frame)")
    s.msg("en", "ru", 445, "scores, alert or none", reply=True)
    s.msg("ru", "rf", 498, "write partial alerts")
    s.msg("da", "sv", 570, "GET /api/replay/status")
    s.msg("da", "sv", 625, "GET /api/replay/partial-alerts")
    s.msg("sv", "rf", 655, "read partial alerts")
    s.msg("ru", "rf", 705, "write the summary file")
    s.msg("ru", "sv", 730, "process ends", reply=True)
    s.msg("sv", "rf", 760, "read the summary file")
    s.self_msg("sv", 780, "status completed, alerts\npublished for /api/explain")
    s.msg("da", "sv", 840, "GET /api/replay/alerts")
    s.msg("sv", "da", 870, "alert list", reply=True)
    s.msg("da", "vm", 900, "AlertHistoryUpdated (event)", asyn=True)
    s.msg("vm", "an", 935, "alerts on the timeline", reply=True)
    return d


@figure
def detection_pipeline():
    d = Diagram("detection_pipeline")
    X, LC, RC = 330, 170, 500
    s = d.start(X, 15)
    frames = d.box("Frames of a log file\nor of an adapter", X, 65, 190, 44)
    how = d.decision("How do the\nframes arrive?", X, 150, 170, 70)
    one = d.box("One frame at a time\n(RealtimeEngine.process_frame)", LC, 250, 210, 44)
    window = d.box("Update the window\nof its identifier", LC, 320, 210, 44)
    layers = d.box("Timing layer, payload layer,\nmodel layer (score of\nthe identifier)", LC, 395, 210, 60)
    fused = d.box("Fused score: 0.35 timing\n+ 0.35 payload + 0.20 model\n+ 0.10 persistence", LC, 480, 210, 60)
    gate = d.decision("Fused score ≥ 0.40\nand cooldown over?", LC, 575, 190, 76)
    alert = d.box("Alert, severity LOW,\nMEDIUM, HIGH or CRITICAL", LC, 670, 210, 44, "red")
    whole = d.box("Whole recording, features\nper identifier in time order", RC, 250, 210, 44, "green")
    score = d.box("Score every frame with\nthe model of its identifier", RC, 320, 210, 44, "green")
    flag = d.box("Flagged (score > 0.5) or\nunresolved, with its reason", RC, 390, 210, 44, "green")
    checks = d.box("Timing fingerprint, patterns,\nwhitelist, correlation", RC, 460, 210, 44, "green")
    bursts = d.box("Merge bursts (8 alerts on\none identifier in 2 s)", RC, 530, 210, 44, "green")
    alerts = d.box("Alerts, severity WARNING,\nHIGH or CRITICAL", RC, 600, 210, 44, "red")
    m = d.merge(X, 750)
    e = d.end(X, 800)
    chain(d, s, frames, how)
    flow(d, how, one, "one by one: replay,\nsimulation, live", exit=L, entry=T)
    flow(d, how, whole, "whole file:\noffline analysis", exit=R, entry=T)
    chain(d, one, window, layers, fused, gate)
    flow(d, gate, alert, "yes")
    flow(d, gate, m, "no", exit=R, entry=T)
    flow(d, alert, m, exit=B, entry=L)
    chain(d, whole, score, flag, checks, bursts, alerts)
    flow(d, alerts, m, exit=B, entry=R)
    flow(d, m, e)
    return d


@figure
def state_vehicle():
    d = Diagram("state_vehicle")
    f = d.box("14 rolling features\nof the frame", 80, 40, 140, 50, "blue")
    s = d.box("RobustScaler", 245, 40, 120, 40, "blue")
    k = d.box("K-Means\n(5 clusters, shared\nby all vehicles)", 410, 40, 140, 60, "purple")
    m = d.box("Cluster to state\nmapping", 580, 40, 130, 50, "purple")
    st = d.box("Driving state:\nparking, idle\nor driving", 580, 160, 130, 60, "yellow")
    iforest = d.box("Isolation Forest of\nthis state and vehicle\n(with its own scaler)", 380, 160, 170, 60, "green")
    g = d.box("Generic model,\nthen a heuristic", 130, 160, 140, 50, "grey")
    chain(d, f, s, k, m, st, iforest)
    d.edge(iforest, g, "no forest\nfor this state",
           "edgeStyle=orthogonalEdgeStyle;rounded=0;html=1;fontSize=11;endArrow=open;endFill=0;dashed=1;endSize=10;")
    return d


@figure
def feature_engineering_pipeline():
    d = Diagram("feature_engineering_pipeline")
    X = 300
    s = d.start(X, 15)
    frame = d.box("Frame of identifier ID\n(timestamp, up to 8 payload bytes)", X, 65, 250, 44)
    window = d.box("Add it to the window of ID\n(last 10 frames of this identifier)", X, 135, 250, 44)
    enough = d.decision("At least 11 frames\nof ID so far?", X, 225, 180, 76)
    fork = d.bar(X, 300, 380)
    timing = d.uml_class("Timing features", 80, 330, 190,
                         ["time_diff", "rolling mean of time_diff", "rolling std of time_diff"], color="blue")
    payload = d.uml_class("Payload features", 300, 330, 240,
                          ["byte_diff", "rolling mean, std and max", "of byte_diff", "changed_bytes_count",
                           "payload_entropy"], color="blue")
    join = d.bar(X, 470, 380)
    keep = d.box("Keep only the features that vary\nfor ID in the training data", X, 520, 250, 44, "green")
    vector = d.box("Vector of up to 9 values\nfor the model of ID", X, 590, 250, 44, "green")
    warm = d.box("Warmup: no features,\nthe frame is not scored", 610, 225, 170, 50, "grey")
    m = d.merge(X, 660)
    e = d.end(X, 705)
    chain(d, s, frame, window, enough)
    flow(d, enough, fork, "yes")
    # bars span 110..490; the two boxes are centred on 175 and 420
    flow(d, fork, timing, exit=(65 / 380, 1), entry=T)
    flow(d, fork, payload, exit=(310 / 380, 1), entry=T)
    flow(d, timing, join, exit=B, entry=(65 / 380, 0))
    flow(d, payload, join, exit=B, entry=(310 / 380, 0))
    chain(d, join, keep, vector, m, e)
    flow(d, enough, warm, "no")
    flow(d, warm, m, exit=B, entry=R)
    return d


@figure
def ml_training_pipeline():
    d = Diagram("ml_training_pipeline")
    X, RX = 210, 670
    s = d.start(X, 15)
    rec = d.box("Recordings of one vehicle\n(listed in the plan file)", X, 65, 250, 44)
    split = d.box("Split by recording: training or holdout\n(no overlap, checked with SHA-256)", X, 135, 280, 44)
    feats = d.box("Compute the 9 features per identifier\non the training recordings", X, 205, 280, 44)
    nxt = d.box("Next identifier", X, 270, 160, 36)
    enough = d.decision("At least 1,000 rows\nand varying features?", X, 355, 200, 80)
    fit = d.box("Fit an Isolation Forest\n(200 trees, seed 42, no scaler)", X, 455, 220, 44, "green")
    thr = d.box("Threshold: 2% of the training rows\n(strict quantile), keep the median", X, 525, 240, 44, "green")
    sparse = d.box("Record it as sparse\nor unmodelled", 420, 455, 150, 44, "grey")
    m1 = d.merge(X, 590)
    left = d.decision("Identifiers left?", X, 650, 150, 56)
    write = d.box("Write models.joblib and manifest.json\nto assets/models_staging/<version>", RX, 65, 270, 44, "yellow")
    score = d.box("Score the holdout recordings,\nwrite the validation report", RX, 135, 270, 44, "yellow")
    ok = d.decision("Evaluation\nacceptable?", RX, 225, 160, 70)
    promote = d.box("Promote to assets/models\n(model file stored with Git LFS)", RX, 320, 250, 44, "green")
    archive = d.box("Archive the replaced files\nwith promotion.json", RX, 390, 250, 44, "green")
    hold = d.box("Hold the\nmodel back", 870, 225, 110, 44, "red")
    m2 = d.merge(RX, 455)
    e = d.end(RX, 500)
    chain(d, s, rec, split, feats, nxt, enough)
    flow(d, enough, fit, "yes")
    flow(d, enough, sparse, "no", exit=R, entry=T)
    chain(d, fit, thr, m1)
    flow(d, sparse, m1, exit=B, entry=R)
    flow(d, m1, left)
    flow(d, left, nxt, "yes", exit=L, entry=L, points=[(50, 650), (50, 270)])
    flow(d, left, write, "no", exit=R, entry=L, points=[(505, 650), (505, 65)])
    chain(d, write, score, ok)
    flow(d, ok, promote, "yes")
    flow(d, ok, hold, "no")
    chain(d, promote, archive, m2, e)
    flow(d, hold, m2, exit=B, entry=R)
    return d


@figure
def ml_comparison_pipeline():
    d = Diagram("ml_comparison_pipeline")
    X = 380
    split = d.box("Production split of the 4 vehicles:\ntraining recordings | holdout recordings", X, 30, 420, 44)
    feats = d.box("9 canonical features per CAN identifier;\nthe same training rows for every model (at most 5,000)", X, 105, 420, 44)
    iforest = d.box("Isolation Forest\n200 trees, no scaler", 150, 190, 200, 44, "green")
    lof = d.box("Local Outlier Factor\n20 neighbours, scaler", X, 190, 200, 44, "green")
    svm = d.box("One Class SVM\nRBF kernel, scaler", 610, 190, 200, 44, "green")
    thr = d.box("Threshold at 2% of the training rows (same rule),\nthen score the holdout recordings", X, 275, 420, 44)
    cmp = d.box("Compare: share of holdout rows flagged,\ntraining time, time to score one frame", X, 350, 420, 44, "yellow")
    flow(d, split, feats)
    for m in (iforest, lof, svm):
        flow(d, feats, m)
        flow(d, m, thr)
    flow(d, thr, cmp)
    return d


@figure
def runtime_inference_pipeline():
    d = Diagram("runtime_inference_pipeline")
    X, RX, LX = 300, 545, 85
    s = d.start(X, 15)
    frame = d.box("CAN frame\n(timestamp, identifier, payload)", X, 60, 230, 44)
    upd = d.box("CanonicalFeatureStream.update()", X, 125, 230, 36)
    enough = d.decision("At least 11 frames\nof this identifier?", X, 205, 190, 72)
    warm = d.box("No model score\n(status: warmup)", LX, 300, 150, 44, "grey")
    status = d.decision("IdModelFamily\n.status(id)", X, 300, 170, 64)
    unres = d.box("No model score\n(status reported\nwith the result)", RX, 300, 160, 56, "grey")
    fifth = d.decision("5th frame of\nthis identifier?", X, 395, 170, 64)
    score = d.box("IdModel.score: raw score,\nnormalised with threshold\nand median", X, 485, 210, 56, "green")
    reuse = d.box("Reuse the last score\nof this identifier", RX, 485, 160, 44, "green")
    m1 = d.merge(X, 560)
    layers = d.box("Timing layer and payload layer", X, 610, 230, 36)
    fuse = d.box("ScoringEngine.score():\nfused score with persistence", X, 670, 230, 44)
    gate = d.decision("Fused score\n≥ 0.40?", X, 755, 150, 64)
    cool = d.decision("Cooldown of 1 s over\nfor this identifier?\n(should_alert)", RX, 755, 200, 90)
    emit = d.box("AlertSystem.emit():\nalert with its severity", RX, 860, 190, 44, "red")
    m2 = d.merge(RX, 930)
    e = d.end(RX, 975)
    chain(d, s, frame, upd, enough)
    flow(d, enough, warm, "no", exit=L, entry=T)
    flow(d, enough, status, "yes")
    flow(d, status, unres, "sparse,\nunmodelled,\nunseen")
    flow(d, status, fifth, "scored")
    flow(d, fifth, score, "yes")
    flow(d, fifth, reuse, "no", exit=R, entry=T)
    flow(d, warm, m1, exit=B, entry=L)
    flow(d, unres, m1, exit=R, entry=R, points=[(645, 300), (645, 560)])
    flow(d, score, m1)
    flow(d, reuse, m1, exit=B, entry=R)
    chain(d, m1, layers, fuse, gate)
    flow(d, gate, cool, "yes")
    flow(d, gate, m2, "no", exit=B, entry=L)
    flow(d, cool, emit, "yes")
    flow(d, cool, m2, "no", exit=R, entry=R, points=[(690, 755), (690, 930)])
    flow(d, emit, m2)
    flow(d, m2, e)
    return d


@figure
def ai_workflow():
    d = Diagram("ai_workflow")
    # overview only: the lookup, the cache and the web search are described in the appendix
    X, LX, RX, FX = 300, 110, 520, 700
    s = d.start(X, 15)
    ask = d.box("Analyst selects an alert", X, 65, 210, 40)
    find = d.box("Find the alert in the current\nanalysis, replay or live session", X, 130, 260, 44)
    ctx = d.uml_class("Build the context of the alert", X - 140, 185, 280,
                      ["measured values and layer scores", "usual behaviour of the identifier",
                       "decoded signals, when a DBC file exists", "known anomaly patterns",
                       "similar past cases"], color="yellow")
    gem = d.decision("Gemini\nanswers?", X, 360, 130, 60)
    olla = d.decision("Local Ollama\nanswers?", RX, 360, 150, 60)
    mg = d.box("Text from Gemini;\nnumbers not in the\ncontext are recorded", LX, 455, 180, 56, "purple")
    mo = d.box("Text from Ollama;\nnumbers not in the\ncontext are recorded", RX, 455, 180, 56, "purple")
    rb = d.box("Rule based\ntemplate", FX, 455, 130, 44, "grey")
    m2 = d.merge(X, 535)
    final = d.box("Show the summary, detail and\nrecommendation with the name\nof the engine that wrote it",
                  X, 600, 260, 60, "green")
    e = d.end(X, 665)
    chain(d, s, ask, find, ctx, gem)
    flow(d, gem, mg, "yes", exit=L, entry=T)
    flow(d, gem, olla, "no")
    flow(d, olla, mo, "yes")
    flow(d, olla, rb, "no", exit=R, entry=T)
    flow(d, mg, m2, exit=B, entry=L)
    flow(d, mo, m2, exit=B, entry=R)
    flow(d, rb, m2, exit=B, entry=R)
    chain(d, m2, final, e)
    return d


@figure
def class_detection_core():
    d = Diagram("class_detection_core")
    ms = d.uml_class("ModelStatus", 10, 16, 130, ["+id : str", "+status : str", "+offline : str", "+live : str"])
    mod = d.uml_class("model_status", 180, 20, 300, [],
                      ["+resolve(model_id) : ModelStatus", "+live_engine(vehicle_id) : RealtimeEngine"],
                      stereotype="module")
    ids = d.uml_class("IDSStatistics", 540, 10, 210, [],
                      ["+on_frame()", "+on_score(fusion_score)", "+on_alert(alert)", "+as_dict() : dict"])
    cf = d.uml_class("CanFrame", 10, 190, 150, ["+timestamp : float", "+can_id : int", "+payload : tuple[int]"],
                     color="grey")
    eng = d.uml_class("RealtimeEngine", 210, 180, 300,
                      ["+vehicle_id : str", "+cfg : RuntimeConfig", "-_family : IdModelFamily",
                       "-_canonical : CanonicalFeatureStream"],
                      ["+process_frame(frame : CanFrame) : dict"], color="green")
    al = d.uml_class("AlertSystem", 550, 190, 340, ["+cooldown_seconds : float"],
                     ["+should_alert(timestamp, can_id, level) : bool",
                      "+emit(timestamp, can_id, level, score, reason) : dict"], color="orange")
    cfs = d.uml_class("CanonicalFeatureStream", 10, 380, 370, [],
                      ["+update(timestamp, can_id, payload) : list[float] | None", "+reset()"], color="orange")
    sc = d.uml_class("ScoringEngine", 410, 380, 230, ["+w_t, w_p, w_m, w_tmp : float", "+high_threshold : float"],
                     ["+score(timing, payload, ml) : dict"], color="orange")
    fam = d.uml_class("IdModelFamily", 670, 380, 220,
                      ["+family : str", "+manifest : dict", "+models : dict[int, IdModel]", "+sparse : set[int]",
                       "+unmodelled : set[int]"],
                      ["+status(can_id) : str", "+score_rows(x, can_ids)", "+score_one(vec, can_id)"],
                      color="purple")
    idm = d.uml_class("IdModel", 680, 610, 200,
                      ["+features : list[str]", "+model : IsolationForest", "+threshold : float", "+median : float"],
                      color="purple")
    d.edge(mod, ms, "", DEPEND)
    d.edge(mod, eng, "builds", DEPEND, exit=(0.3, 1), entry=(0.3, 0))
    d.edge(ids, eng, "counts results of", DEPEND, exit=B, entry=(0.8, 0))
    # exits placed level with the centres of CanFrame and AlertSystem, so both lines are straight
    d.edge(eng, cf, "", DEPEND, exit=(0, 0.42), entry=R)
    d.edge(eng, al, "", COMPOSE, exit=(1, 0.457), entry=L)
    d.edge(eng, cfs, "", COMPOSE, exit=(0.2, 1), entry=T)
    d.edge(eng, sc, "", COMPOSE, exit=(0.7, 1), entry=T)
    d.edge(eng, fam, "", AGGREGATE, exit=(1, 0.85), entry=T)
    d.edge(fam, idm, "1..*", COMPOSE, exit=B, entry=T)
    return d


@figure
def deployment():
    d = Diagram("deployment")
    # the server box spans x 260..620, so each store below it gets a straight vertical line
    d.group("«device» Analyst workstation (Windows 10/11)", 10, 10, 640, 330, "grey")
    exe = d.box("«artifact»\nCANvisionNative.exe\n(.NET Framework 4.8)", 120, 120, 170, 60, "blue", rounded=False)
    d.group("«execution environment» Python process (uvicorn)", 240, 50, 400, 120, "orange")
    srv = d.box("«artifact»\nbackend.api.server (port 8765)", 440, 120, 360, 44, "orange", rounded=False)
    db = d.cylinder("SQLite file\n(sessions, alerts)", 300, 270, 120, 70)
    mdl = d.folder("assets/models\n(manifests, models)", 440, 270, 130, 60, "yellow")
    oll = d.cube("Ollama\n(optional)", 580, 270, 100, 56, "purple")
    gem = d.cloud("Google Gemini API", 740, 45, 150, 64, "purple")
    usb = d.cube("USB CAN adapter\n(slcan bridge, PCAN)", 740, 410, 170, 60, "green")
    car = d.cube("Vehicle or bench rig\n(CAN bus, 500 kbit/s)", 740, 520, 170, 60, "green")
    flow(d, exe, srv, "HTTP")
    flow(d, srv, db, exit=(40 / 360, 1), entry=T)
    flow(d, srv, mdl, exit=B, entry=T)
    flow(d, srv, oll, "HTTP", exit=(320 / 360, 1), entry=T)
    flow(d, srv, gem, "HTTPS", exit=(1, 0.1), entry=B)
    flow(d, srv, usb, "USB (python-can)", exit=(1, 0.75), entry=T)
    d.edge(usb, car, "CAN", "edgeStyle=orthogonalEdgeStyle;rounded=0;html=1;fontSize=11;endArrow=none;")
    return d


@figure
def domain_model():
    """Analysis model: the concepts of the domain and their associations."""
    d = Diagram("domain_model")
    W = 200
    veh = d.uml_class("Vehicle", 20, 20, W, ["name"])
    prof = d.uml_class("VehicleProfile", 300, 20, W, ["bitrate", "DBC files", "complete : bool"])
    sig = d.uml_class("Signal", 580, 20, W, ["name", "value", "unit"])
    vm = d.uml_class("VehicleModel", 20, 190, W, ["family", "status", "manifest"])
    rec = d.uml_class("Recording", 300, 190, W, ["file", "format", "SHA-256 fingerprint"])
    fr = d.uml_class("Frame", 580, 190, W, ["timestamp", "CAN identifier", "payload (0 to 8 bytes)"])
    idm = d.uml_class("IdentifierModel", 20, 370, W, ["CAN identifier", "features", "threshold", "median"])
    ses = d.uml_class("Session", 300, 370, W, ["source : offline, replay or live", "frames scored",
                                                "frames flagged", "unresolved frames by reason"])
    rep = d.uml_class("Report", 580, 370, W, ["format : PDF or CSV", "generated"])
    al = d.uml_class("Alert", 300, 560, W, ["time", "CAN identifier", "severity", "score", "dominant layer",
                                            "reason"])
    ex = d.uml_class("Explanation", 580, 560, W, ["engine", "summary", "likely cause", "recommendation"])
    def a(s, t, label, m1, m2, way, style=ASSOC, **kw):
        d.end_labels(d.edge(s, t, label, style, **kw), m1, m2, way)

    a(veh, prof, "decoded with", "1", "0..1", "lr", exit=R, entry=(0, 0.3))
    a(veh, vm, "scored by", "1", "0..1", "tb", exit=B, entry=T)
    a(vm, idm, "", "1", "1..*", "tb", COMPOSE, exit=B, entry=T)
    a(rec, veh, "recorded on", "*", "1", "bt", exit=(0.1, 0), entry=(0.8, 1))
    a(rec, fr, "", "1", "1..*", "lr", COMPOSE, exit=R, entry=L)
    a(prof, sig, "defines", "1", "*", "lr", exit=R, entry=L)
    a(fr, sig, "decoded into", "1", "*", "bt", exit=T, entry=B)
    a(ses, rec, "analyses", "*", "0..1", "bt", exit=T, entry=B)
    a(ses, vm, "uses", "*", "1", "rl", exit=(0, 0.3), entry=(1, 0.7))
    a(ses, al, "", "1", "*", "tb", COMPOSE, exit=B, entry=T)
    a(al, ex, "explained by", "1", "0..1", "lr", exit=(1, 0.38), entry=L)
    a(rep, ses, "exports", "*", "1", "rl", exit=L, entry=(1, 0.34))
    return d


@figure
def data_model():
    """Physical data model of the SQLite store (backend/db/store.py)."""
    d = Diagram("data_model")
    ses = d.uml_class("sessions", 300, 20, 230,
                      ["PK id : TEXT", "started_at : REAL", "ended_at : REAL",
                       "source : TEXT (live, replay, inject)", "frame_count : INTEGER", "anomaly_count : INTEGER"],
                      stereotype="table", color="yellow")
    lf = d.uml_class("live_frames", 20, 250, 250,
                     ["PK id : INTEGER", "session_id : TEXT", "timestamp : REAL", "can_id : INTEGER",
                      "b0 ... b7 : INTEGER", "anomaly : INTEGER (1 or -1)",
                      "user_label : TEXT", "created_at : REAL"],
                     stereotype="table", color="yellow")
    ah = d.uml_class("alert_history", 560, 250, 270,
                     ["PK id : INTEGER", "session_id : TEXT", "timestamp : REAL", "can_id : TEXT",
                      "severity : TEXT", "score : REAL", "attack_type : TEXT", "reason : TEXT",
                      "temporal_pattern : TEXT", "plausibility_passed : INTEGER", "timing_anomaly : INTEGER",
                      "recommended_response : TEXT", "created_at : REAL"],
                     stereotype="table", color="yellow")
    d.end_labels(d.edge(ses, lf, "", ASSOC, exit=(0.2, 1), entry=T), "1", "*", "tb")
    d.end_labels(d.edge(ses, ah, "", ASSOC, exit=(0.8, 1), entry=T), "1", "*", "tb")
    d.note("session_id refers to sessions.id\n(by convention: no FOREIGN KEY\nconstraint is declared).\n"
           "Indexes: live_frames on session_id,\ncan_id, timestamp, anomaly;\nalert_history on session_id, severity.",
           20, 470, 250, 110)
    return d


@figure
def state_model_status():
    """Life cycle of a vehicle model under the clean pipeline (Table of model statuses)."""
    d = Diagram("state_model_status")
    X = 300
    s = d.start(X, 20)
    run = d.box("Training run", X, 75, 200, 40, "blue")
    built = d.decision("Identifier\nmodels built?", X, 160, 150, 64)
    none = d.box("No final model\nrefused", 80, 160, 150, 50, "grey")
    staged = d.box("Staged\n(assets/models_staging)", X, 255, 200, 50, "blue")
    hold = d.decision("Holdout\nrecording?", X, 345, 150, 64)
    notval = d.box("Not validated (no holdout)\nrefused offline; live uses the\nfirst design, with a label", 590, 345,
                   230, 64, "yellow")
    evalu = d.box("Evaluated on the holdout", X, 440, 200, 40, "blue")
    ok = d.decision("Evaluation\nacceptable?", X, 525, 150, 64)
    held = d.box("Held back\nrefused offline and live", 590, 525, 200, 50, "red")
    prod = d.box("In production\nused offline and live", X, 625, 200, 50, "green")
    arch = d.box("Archived\n(assets/models_archive)", X, 725, 200, 50, "grey")
    e = d.end(X, 800)
    chain(d, s, run, built)
    flow(d, built, none, "no", exit=L, entry=R)
    flow(d, built, staged, "yes")
    flow(d, staged, hold, "validate")
    flow(d, hold, notval, "no", exit=R, entry=L)
    flow(d, hold, evalu, "yes")
    flow(d, evalu, ok)
    flow(d, ok, held, "no", exit=R, entry=L)
    flow(d, ok, prod, "yes: promote")
    flow(d, prod, arch, "replaced by a newer\npromoted version")
    flow(d, arch, e)
    d.note("Outside this life cycle, from the first design:\nLegacy (refused offline, live with a label)\n"
           "and General (vehicle without its own model).", 520, 640, 300, 64)
    return d


@figure
def component_diagram():
    """Components of the client and the backend, and the interfaces between them."""
    d = Diagram("component_diagram")

    def comp(label, cx, cy, w=170, h=52, color="orange"):
        return d.box("«component»\n" + label, cx, cy, w, h, color, rounded=False)

    d.group("Desktop client", 10, 10, 1000, 120, "blue")
    views = comp("Views (XAML)", 130, 80, color="blue")
    vms = comp("ViewModels", 350, 80, color="blue")
    svc = comp("Client services", 570, 80, 180, color="blue")
    pdf = comp("PDF and CSV export", 820, 80, 170, color="blue")
    d.group("Backend (local Python process)", 10, 180, 1000, 460, "orange")
    api = comp("REST API\n(FastAPI)", 570, 250, 170, 60)
    exp = comp("Explanation engine", 100, 370, 170)
    off = comp("Offline analyzer", 300, 370, 160)
    rep = comp("Replay runner", 480, 370, 150)
    db = comp("Persistence\n(SQLite store)", 680, 370, 170, 56)
    hw = comp("Hardware interface\n(python-can)", 880, 370, 180, 56)
    parser = comp("Log parser", 300, 490, 150)
    eng = comp("Runtime engine\n(features, scoring, alerts)", 520, 490, 200, 60)
    dec = comp("Decoding\n(DBC, signal discovery)", 860, 490, 180, 56)
    mm = comp("Model management\n(manifest, status, promotion)", 400, 595, 220, 52)
    gem = d.cloud("Gemini API", 80, 720, 130, 64, "purple")
    oll = d.cube("Ollama", 230, 720, 100, 50, "purple")
    files = d.cylinder("Model files\n(assets/models)", 400, 725, 140, 70)
    sqlite = d.cylinder("SQLite file", 680, 725, 120, 70)
    adapter = d.cube("CAN adapter", 1110, 370, 110, 50, "green")

    def dep(s, t, label="", **kw):
        return d.edge(s, t, label, DEPEND, **kw)

    dep(views, vms, "binding")
    dep(vms, svc)
    dep(vms, pdf, exit=(0.5, 0), entry=(0.5, 0), points=[(350, 40), (820, 40)])
    dep(svc, api, "HTTP + JSON", exit=B, entry=T)
    for t in (exp, off, rep, db, hw):
        dep(api, t, exit=B, entry=T)
    dep(off, parser, exit=B, entry=T)
    dep(off, mm, exit=L, entry=L, points=[(200, 370), (200, 595)])
    dep(rep, parser, exit=(0.3, 1), entry=(0.8, 0))
    dep(rep, eng, exit=(0.7, 1), entry=(0.3, 0))
    dep(hw, eng, exit=(0.2, 1), entry=(0.85, 0), points=[(844, 430), (590, 430)])
    dep(hw, dec, exit=(0.6, 1), entry=(0.7, 0))
    dep(eng, mm, exit=B, entry=(0.85, 0))
    dep(mm, files, exit=B, entry=T)
    dep(db, sqlite, exit=B, entry=T)
    dep(exp, gem, "HTTPS", exit=(0.2, 1), entry=T)
    dep(exp, oll, "HTTP", exit=(0.8, 1), entry=T)
    dep(hw, adapter, "USB", exit=R, entry=L)
    return d


@figure
def class_client():
    """Main classes of the desktop client (MVVM)."""
    d = Diagram("class_client")
    obs = d.uml_class("ObservableObject", 40, 10, 220, [], [], "grey", stereotype="CommunityToolkit.Mvvm")
    base = d.uml_class("ViewModelBase", 40, 100, 220, [], [], "green", italic=True)
    main = d.uml_class("MainWindowViewModel", 360, 10, 220, [], [], "green")
    nav = d.uml_class("NavigationService", 640, 10, 220, ["+Tabs", "+NavigateCommand"], [], "orange")
    sec = d.uml_class("SectionViewModel", 20, 210, 260,
                      ["+Key : SectionKey", "+Snapshot : VehicleSnapshot", "#VehicleDataService",
                       "#ShowsCapture : bool"], [], "green", italic=True)
    names = ["Home", "Dashboard", "Telemetry", "Diagnostics", "LogPlayback", "AnomalyIntel", "Settings",
             "HardwareSetup"]
    vms = [d.uml_class(f"{n}ViewModel", 360, 150 + i * 38, 200, [], [], "green") for i, n in enumerate(names)]
    data = d.uml_class("VehicleDataService", 20, 520, 330,
                       ["+CurrentSnapshot : VehicleSnapshot", "+AlertHistory", "+DataUpdated : event",
                        "+AlertHistoryUpdated : event", "+AppStateChanged : event"],
                       ["+StartOfflineAnalysisAsync(path, vehicleId)", "+TriggerBackendReplayAsync(path, vehicleId)",
                        "+ConnectHardwareAsync(type, channel, bitrate, id)"], "orange")
    api = d.uml_class("PythonApiClient", 380, 520, 270, [],
                      ["+AnalyzeLogsAsync(files, modelId)", "+StartReplayAsync(path, limit, vehicleId)",
                       "+GetAlertExplanationAsync(index)", "+DiscoverSignalsAsync(path, vehicleId)",
                       "+DescribeDatasetAsync(path, vehicleId)"], "orange")
    sel = d.uml_class("ModelSelectionService", 690, 520, 240,
                      ["+SelectedModel : TrainedModelInfo", "+SelectionChanged : event"], ["+LoadAsync()"], "orange")
    imp = d.uml_class("CanLogImportService", 380, 740, 270, [], ["+ParseFileAsync(path) : CanImportResult"], "orange")
    pdf = d.uml_class("PdfReportBuilder", 690, 740, 240, [], ["+Build(alerts, path, context)"], "orange",
                      stereotype="static")
    snap = d.uml_class("VehicleSnapshot", 20, 730, 160, [], [], "grey")
    alert = d.uml_class("RuntimeAlertEvent", 20, 790, 230, ["+CanId, +Severity, +Score", "+Reason, +BackendIndex"],
                        [], "grey")
    state = d.uml_class("AppState", 690, 850, 240,
                        ["NoDataset, DatasetLoaded,", "Analyzing, AnalysisComplete,", "LiveSession"], [], "grey",
                        stereotype="enumeration")
    d.edge(base, obs, "", GENERALIZE, exit=T, entry=B)
    d.edge(sec, base, "", GENERALIZE, exit=(0.5, 0), entry=B)
    d.edge(main, base, "", GENERALIZE, exit=L, entry=(1, 0.3), points=[(320, 23), (320, 108)])
    d.edge(main, nav, "", COMPOSE, exit=R, entry=L)
    for v in vms:
        d.edge(v, sec, "", GENERALIZE, exit=L, entry=R)
    d.edge(sec, data, "uses", DEPEND, exit=(0.3, 1), entry=(0.3, 0))
    d.edge(sec, sel, "uses", DEPEND, exit=(0.9, 1), entry=T, points=[(254, 490), (810, 490)])
    d.edge(data, api, "calls", DEPEND, exit=R, entry=L)
    d.edge(imp, api, "calls", DEPEND, exit=T, entry=B)
    d.edge(vms[5], pdf, "builds the report", DEPEND, exit=R, entry=L, points=[(670, 353), (670, 765)])
    d.edge(data, snap, "", COMPOSE, exit=(0.2, 1), entry=T)
    d.edge(data, alert, "*", COMPOSE, exit=(0.5, 1), entry=(0.6, 0))
    d.edge(data, state, "", DEPEND, exit=(0.9, 1), entry=L, points=[(317, 896)])
    return d


# ── Chapter 4 ───────────────────────────────────────────────────────────────

@figure
def repo_structure():
    d = Diagram("repo_structure")
    rows = [
        (0, "can_project/", ""),
        (1, "UI/", "XAML views and controls"),
        (1, "ViewModels/", "one ViewModel per screen"),
        (1, "Services/", "API client, data service, import, PDF"),
        (1, "Models/", "API contracts, runtime models"),
        (1, "tests/CANvisionNative.Tests/", "xUnit tests (80)"),
        (1, "backend/", ""),
        (2, "api/", "server.py (FastAPI endpoints)"),
        (2, "decoding/", "DBC decoding, vehicle profiles, signal discovery"),
        (2, "ml/", "features, runtime engine, training, explainer"),
        (2, "offline/", "offline analysis, dataset facts"),
        (2, "hardware/", "python-can interface, recorder"),
        (2, "tests/", "pytest tests (318)"),
        (1, "assets/", ""),
        (2, "models/", "models in production (Git LFS)"),
        (2, "models_staging/", "trained models awaiting evaluation"),
        (2, "models_archive/", "replaced models"),
        (2, "dbc_files/", "DBC files of the vehicle profiles"),
        (2, "EV-CANlogs-main/, road/, Train/", "recordings"),
        (1, "arduino_bench_rig/", "firmware of the bench rig"),
    ]
    colors = {0: "blue", 1: "yellow", 2: "green"}
    parents: dict[int, tuple[str, float]] = {}
    for i, (level, name, desc) in enumerate(rows):
        y = 20 + i * 30
        w = 30 + 7 * len(name)
        x = 20 + level * 40
        box = d.box(name, x + w / 2, y + 12, w, 24, colors[level],
                    extra="arcSize=20;" + ("fontStyle=1;" if not desc else ""))
        if desc:
            d.text(desc, 380, y, 340, 24, extra="fontColor=#333333;")
        if level:
            pid, pw = parents[level - 1]
            d.edge(pid, box, "", "edgeStyle=orthogonalEdgeStyle;rounded=0;html=1;endArrow=none;strokeColor=#999999;",
                   exit=(16 / pw, 1), entry=L)
        parents[level] = (box, w)
    return d


@figure
def export_workflow():
    d = Diagram("export_workflow")
    X, LC, RC = 300, 150, 450
    s = d.start(X, 15)
    lst = d.box("Alert list shown in Anomaly Intel", X, 65, 230, 40)
    which = d.decision("Which export?", X, 140, 150, 60)
    rows = d.box("One row per alert: time, CAN ID,\nseverity, pattern, score, reason,\n"
                 "knowledge base match, explanation", LC, 240, 230, 60, "green")
    fmt = d.box("Numbers written in a fixed format\n(independent of the\nWindows language)", LC, 325, 230, 60,
                "green")
    csv = d.doc("alerts_<date>.csv", LC, 405, 170, 50)
    build = d.box("PdfReportBuilder.Build()", RC, 240, 210, 40, "orange")
    a4 = d.box("A4 report: header, summary\nby severity, table of the alerts", RC, 320, 230, 50, "orange")
    pdf = d.doc("CANvision_AlertReport_<date>.pdf", RC, 405, 230, 50)
    m = d.merge(X, 470)
    e = d.end(X, 515)
    chain(d, s, lst, which)
    flow(d, which, rows, "EXPORT CSV", exit=L, entry=T)
    flow(d, which, build, "EXPORT PDF", exit=R, entry=T)
    chain(d, rows, fmt, csv)
    chain(d, build, a4, pdf)
    flow(d, csv, m, exit=B, entry=L)
    flow(d, pdf, m, exit=B, entry=R)
    flow(d, m, e)
    return d


# ── Chapter 5 ───────────────────────────────────────────────────────────────

@figure
def validation_workflow():
    d = Diagram("validation_workflow")
    d.group("Pass 1: interface audit", 10, 10, 220, 460, "blue")
    d.group("Pass 2: root causes", 260, 10, 240, 460, "yellow")
    d.group("Pass 3: correction", 530, 10, 260, 460, "green")
    s = d.start(120, 65)
    use = d.box("Use every screen and\ncontrol, also in the\nwrong order", 120, 130, 180, 60)
    fix1 = d.box("Fix the problems found", 120, 210, 180, 40)
    replay = d.box("Replay the Kia EV6\nrecording (97,741 frames)", 380, 80, 190, 44, "yellow")
    take = d.box("Take an unexplained alert\nand find the layer that\ndominates its score", 380, 165, 190, 60,
                 "yellow")
    left2 = d.decision("Alerts left\nunexplained?", 380, 260, 150, 64, "yellow")
    repro = d.box("Reproduce a suspected\ndefect on demand", 660, 80, 190, 44, "green")
    cause = d.box("Find its cause in the\ncode and fix it", 660, 150, 190, 44, "green")
    again = d.box("Run the same test again", 660, 215, 190, 36, "green")
    left3 = d.decision("Defects left?", 660, 290, 140, 56, "green")
    full = d.box("Full run: import, replay,\ndetection, explanation,\nexport", 660, 370, 190, 56, "green")
    e = d.end(660, 440)
    chain(d, s, use, fix1)
    flow(d, fix1, replay, exit=B, entry=L, points=[(120, 250), (245, 250), (245, 80)])
    chain(d, replay, take, left2)
    flow(d, left2, take, "yes", exit=R, entry=R, points=[(490, 260), (490, 165)])
    flow(d, left2, repro, "no", exit=B, entry=L, points=[(380, 360), (515, 360), (515, 80)])
    chain(d, repro, cause, again, left3)
    flow(d, left3, repro, "yes", exit=R, entry=R, points=[(775, 290), (775, 80)])
    flow(d, left3, full, "no")
    flow(d, full, e)
    return d


@figure
def mf4_workflow():
    d = Diagram("mf4_workflow")
    X, RX = 190, 540
    s = d.start(X, 15)
    open_ = d.box("Open the MF4 file\nwith asammdf", X, 65, 200, 44)
    nxt = d.box("Next channel group", X, 130, 200, 36)
    holds = d.decision("Group holds\nCAN frames?", X, 215, 160, 70)
    extract = d.box("Extract timestamp,\nidentifier and payload", X, 305, 200, 44, "green")
    m1 = d.merge(X, 370)
    left = d.decision("Groups left?", X, 430, 140, 56)
    merge = d.box("Merge the groups\nand sort by timestamp", RX, 65, 220, 44)
    compare = d.box("Compare the number of frames\nwith the metadata of the file", RX, 135, 220, 44)
    equal = d.decision("Counts equal?", RX, 215, 140, 60)
    stream = d.box("Common frame stream\n(97,741 frames for the\nKia EV6 file)", RX, 305, 190, 56, "green")
    missing = d.box("Look for the missing\nframes before using\nthe file", 720, 305, 150, 56, "red")
    m2 = d.merge(RX, 380)
    e = d.end(RX, 425)
    chain(d, s, open_, nxt, holds)
    flow(d, holds, extract, "yes")
    flow(d, holds, m1, "no, empty\ntemplate", exit=R, entry=R, points=[(320, 215), (320, 370)])
    chain(d, extract, m1, left)
    flow(d, left, nxt, "yes", exit=L, entry=L, points=[(40, 430), (40, 130)])
    flow(d, left, merge, "no", exit=R, entry=L, points=[(380, 430), (380, 65)])
    chain(d, merge, compare, equal)
    flow(d, equal, stream, "yes")
    flow(d, equal, missing, "no", exit=R, entry=T)
    flow(d, stream, m2)
    flow(d, missing, m2, exit=B, entry=R)
    flow(d, m2, e)
    return d


@figure
def bugfix_timeline():
    d = Diagram("bugfix_timeline")
    top = [("Root cause analysis\n15,945 alerts,\nall explained", "yellow"),
           ("Fix 1\nvehicle model\nselection", "blue"), ("Fix 2\ndriving state\nclassification", "blue"),
           ("Fix 3\nattribution of\nthe reason", "blue"), ("Fix 4\none parser\nfor replay", "blue")]
    bottom = [("Full run through\nthe application", "green"), ("Fix 5\npolling timer\nleft stopped", "blue"),
              ("Fix 6\nstale explanation\ncache", "blue"), ("Corrected first pipeline\n11,971 alerts", "orange")]
    ids = [d.box(label, 75 + i * 150, 50, 130, 60, color) for i, (label, color) in enumerate(top)]
    ids += [d.box(label, 675 - i * 150, 160, 130, 60, color) for i, (label, color) in enumerate(bottom)]
    chain(d, *ids)
    return d


def main(names: list[str]) -> None:
    for name in names or list(FIGURES):
        d = FIGURES[name]()
        png = export(d.save(HERE))
        shutil.copyfile(png, OUT / png.name)
        print(f"{name}: {png.name}")


if __name__ == "__main__":
    main(sys.argv[1:])
