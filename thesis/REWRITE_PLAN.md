# Thesis rewrite: plan, rules and verified facts

Working file for the final rewrite of the report (started 2026-09-27). Every number
written into the thesis must appear in section 3 with its source, or be measured
and added there first.

## 1. Writing rules

1. **No dash punctuation.** No `---`, no `--` used as a dash, no Unicode `—` or `–`,
   no ` - ` between words. A parenthetical goes in commas or parentheses, or becomes
   its own sentence. Numeric ranges are written with "to" ("0 to 1", "2025/2026").
   Hyphens stay only inside proper names and fixed technical terms (python-can,
   ISO-TP); ordinary compounds are rephrased where a natural form exists
   ("real time", "per CAN identifier").
2. **A student's voice.** First person plural ("we"), as in ESPRIT reports. Plain,
   direct sentences of varied length. No filler openers ("It is worth noting",
   "In today's world"), no stacked triads, no "not only ... but also", no words such
   as delve, robust, seamless, leverage, crucial, pivotal, comprehensive, landscape,
   showcase, foster, empower, streamline, cutting edge, state of the art, testament.
   No sentence that praises the work ("the most important chapter"); the facts do that.
3. **Honesty.** Anomalies are "flagged frames" or "anomalies", never "attacks",
   unless the data carries attack labels. Holdout flagged rates are not
   false-positive rates. No precision, recall or detection rate is claimed without
   labelled data. Anything not tested (live hardware with a real vehicle) is stated
   as not tested.
4. **History is labelled as history.** Measurements taken on the first pipeline
   (the 97,741-frame Kia EV6 correction phase) stay valid as measurements of that
   pipeline and are presented as such; the final system is described as it is now.

## 2. Chapter plan and progress

| Part | Main changes | Status |
|---|---|---|
| Ch. 1 General framework | rewritten 2026-09-27 ("we", no dashes, final system facts, model rebuild phase added). Figure `project_timeline.png` still shows the old timeline: add the model rebuild phase and the final release | ✅ text, ⬜ figure |
| Ch. 2 Requirements | rewritten 2026-09-27: FR4 now "score, flag, report unresolved"; FR9 python-can adapters (ELM327 claim dropped, it is not slcan); new FR12 (signal discovery + dataset card) and FR13 (model status); NFR1 split offline/live; new risks (generalisation, live speed); `\todofill` on Gantt dates removed. TO DO: student confirms Gantt week ranges (rebuild bar placed 21 to 24 by estimate); Ch. 5 must contain the FR12 check on the Jaguar holdout; traceability refs to Ch. 5 labels (Fix 1, Fix 4, Fix 6, tab:before-after, tab:rootcause, fig:chart-severity) must survive the Ch. 5 rewrite | ✅ |
| Ch. 3 Design | rewritten 2026-09-27: two detection paths (frame by frame fusion 0.35/0.35/0.20/0.10, alert 0.40; offline per ID flags + fingerprint, patterns, whitelist, correlation, burst merge 8 in 2 s); first design (K-Means states) kept as sec:impl-state with its three weaknesses; final design (9 features, window 10, 1,000 rows, 2% strict quantile, 200 trees, seed 42, no scaler); manifest checks as the code really does them (no hash check at load); status table; "microseconds" replaced by measured 24 to 42 ms; 52 endpoints; ELM327 dropped. FIGURES TO REDRAW: detection_pipeline.png, feature_engineering_pipeline.png (9 features), ml_training_pipeline.png (split by recording, staging, manifest, holdout, promotion), runtime_inference_pipeline.png (no state step), class_detection_core.png (IdModelFamily, model status resolver, IDSStatistics). state_vehicle.png stays (first design). CHECK: Appendix B table tab:app-fusion-config must show 0.35/0.35/0.20/0.10, alert 0.40, 0.30/0.55/0.80/1.00, cooldown 1 s | ✅ text, ⬜ figures |
| Ch. 4 Implementation | rewritten 2026-09-27: model management section, capture description section (signal discovery + dataset card), USB device detection, real time playback clock, vehicle profiles vs models, bench rig firmware (described, not claimed as tested), CSV locale bug reported as FIXED. New screenshots f01, f02, f02b, f03, f04, f07, f08 captured from the final app on the Jaguar holdout (old 01/03/04/07b/08c no longer used by Ch. 4). Code fixes made while capturing them: CSV exports use invariant numbers (3 screens), invented bus load removed, Telemetry status/activity in capture mode, Diagnostics peak score, DoS burst needs >= 20 msg/s, explanation texts and LLM prompt no longer assert attacks. TO DO: Appendix D still shows old 02_dashboard_live.png and says the CSV issue is open | ✅ |
| Ch. 5 Validation | rewritten 2026-09-27: 4 stages; iteration 1 (six fixes, before/after, 99.92% driving corrected from 99.93%); iteration 2 (protocol, holdout table tab:holdout-results, held back models, consistency checks, app check on the Jaguar holdout = FR12 evidence, display problems found and fixed, speed table tab:perf-live); automated tests (309 + 80); readiness; limits; future work. All labels referenced elsewhere kept. FIGURE TO CHECK: bugfix_timeline.png may still say "Release Candidate" | ✅ |
| General conclusion, introduction, abstract, résumé | rewritten 2026-09-27 from the final chapters (résumé in French, same rules). Acknowledgements: punctuation only (student's own text) | ✅ |
| Appendices | rewritten 2026-09-27. A: 52 endpoints, checked against server.py (script). B: fusion table checked against runtime_config.py; offline path = model thresholds; second config only for /api/validation/score_file; ELM327 dropped. C: corpus of the final models (tab:app-final-corpus, totals 3,436,061 / 1,130,500) + first pipeline corpus as history; Leaf 2019 source = CSS Electronics (README). D: new Settings screenshot, CSV export re-read (339 rows x 9 columns), PDF rebuilt with the app's PdfReportBuilder; old live dashboard screenshot removed; unverified claim about 0x19/0x13 removed. E: sources corrected | ✅ |

## 3. Verified facts (with sources)

### Final models (clean-2-002, promoted at commit 9029fdd, 2026-09-24)
Source: `assets/models/<family>/manifest.json`, `corpus.json`,
`assets/models_staging/clean-2-002/analysis/validation_and_comparison.md`.

- One scikit-learn IsolationForest per CAN identifier, 200 trees, random_state 42,
  no scaler, manifest schema 3.
- Features (canonical-1, window 10, per identifier): time_diff, rolling mean and std
  of time_diff, byte_diff, rolling mean, std and max of byte_diff,
  changed_bytes_count, payload_entropy (9 features; constant ones are dropped per ID).
- Calibration: empirical_quantile_strict, target 2% of training rows; threshold is
  the (k+1)th smallest training score, k = floor(0.02 x rows); flagged iff the raw
  score is below it. Normalised score: 0.5 at the threshold, 0 at the training
  median, 1 at most anomalous; flagged iff above 0.5.
- A CAN ID needs at least 1,000 training rows (MIN_ID_ROWS) to get a model. Frames
  are unresolved (not scored) when: warmup (fewer than 11 frames of that ID so far),
  sparse_id, unmodelled_id, unseen_id.

| Family | CAN ID models | Training recordings / frames | Holdout recording / frames | Holdout flagged of scored |
|---|---|---|---|---|
| jaguar_ipace | 46 | 3 / 233,598 | canbus_turningon_quickly.csv / 50,361 | 1,249 / 40,477 (3.09%) |
| kia_ev6 | 161 | 2 / 448,198 | Vehicle everthing on.asc / 438,170 | 11,109 / 429,524 (2.59%) |
| nissan_leaf_2019 | 12 | 8 / 1,317,070 | 00000001-61D9D9BA.MF4 / 491,969 | 2,951 / 491,797 (0.60%) |
| road_ambient | 77 | 10 / 1,437,195 | ambient_highway_street_driving_long.log / 150,000 (capped) | 8,982 / 147,485 (6.09%) |

- Holdout rates are flagged rates on unlabelled recordings assumed normal, not
  false-positive rates.
- road_ambient: CAN ID 0x193 is static in every training recording and changes in
  the highway holdout; 58% of its holdout rows are flagged (coverage difference,
  threshold not tuned on the holdout).
- Not promoted: mg_zs_ev held back (about 78% of holdout rows on CAN IDs absent from
  training; 43.60% flagged); hyundai_ioniq5, kaggle_normal, tesla unvalidated (one
  recording each, no holdout); skoda_enyaq no clean model; nissan_leaf excluded.
- Calibration re-derived from training rows for every CAN ID model: 0 mismatches.
  Train/holdout overlap: 0 for every family.
- Jaguar holdout in the app (2026-09-27): 50,361 frames, 40,477 scored,
  9,884 unresolved (sparse_id 8,451, warmup 1,368, unseen_id 65), 1,249 flagged,
  339 grouped alerts, flagged scores 0.500 to 0.935.

### Performance (Source: `backend/ml/docs/clean2_performance.md`)
- One per CAN ID model call: about 24 to 42 ms (one row, 200 trees).
- Live path (model on every 5th frame per ID) sustains about 115 to 260 frames/s.
- Real time factor at N = 10,000: jaguar_ipace 0.09x, kia_ev6 0.50x,
  nissan_leaf_2019 2.10x, road_ambient 0.09x. Buses above about 260 frames/s are
  not scored in real time.
- Offline: 491,969 Leaf frames in 187 s; the 50,361-frame Jaguar file in 16 s.

### Algorithm comparison (2026-10-01, Section 5.5)
Source: `backend/ml/outputs/validation_reports/algorithm_comparison.json`, written by
`python -m backend.ml.validation.compare_algorithms --cap 5000`. Same production split, same 9 canonical
features, one model per identifier with a final model (296), at most 5,000 evenly spaced training rows per
identifier for all three, production threshold rule (k = floor(0.02 n)), holdout fully scored. No labels.
- Holdout rows flagged, IF / LOF / OCSVM: Jaguar 3.37 / 13.09 / 13.98 %; Kia EV6 2.58 / 2.60 / 3.46 %;
  Leaf 2019 0.48 / 1.47 / 2.04 %; ROAD 6.39 / 3.40 / 6.67 %. Means 3.21 / 5.14 / 6.54 %.
- Training time, 4 vehicles: 137.6 / 40.9 / 16.8 s. One frame (median of family medians): 23.4 / 0.97 / 0.42 ms.
- Final forests, sample weighted split share: rolling_std_time_diff 21.7, rolling_mean_time_diff 21.6,
  time_diff 21.1 (timing 64.4 %), rolling_std_byte_diff 7.2, rolling_mean_byte_diff 7.1,
  rolling_max_byte_diff 6.7, payload_entropy 5.9, byte_diff 5.5, changed_bytes_count 3.2.
- Do NOT write that LOF or the SVM were rejected for prediction cost: they are faster. IF was kept for fewer
  and more even false alarms on unseen normal traffic. Charts: images/graphs/make_ml_comparison.py.

### Tests (2026-09-27)
- Backend: 306 pytest tests pass. Desktop client: 80 xUnit tests pass.
  Release build: 0 warnings, 0 errors.

### First pipeline (history, measured before the clean rebuild)
Source: current Chapter 5. Kia EV6 UDS recording 00000158-64CBC290.MF4, 97,741
frames; 15,945 baseline alerts (16.3%); root cause shares ML 61.42%, timing 31.51%,
payload 7.07%; six defects fixed. Keep only as the first iteration.

### Bench rig test (2026-09-12, session 4c8234ef; code checked 2026-09-28)
- Rig: 2x Arduino Uno + 2x MCP2515/TJA1050, breadboard bus, 120 ohm termination, 500 kbit/s.
  Firmware in `arduino_bench_rig/`: simulator sends 0x316 speed=60 every 20 ms, 0x3F9 SOC=78
  every 200 ms (55 frames/s), 0x666 every 20 s from 35 s after power on; bridge speaks slcan.
- Step 1 (`arduino_bench_rig/test_bus.py`, python-can slcan): 0x316, 0x3F9 and 0x666 received
  with the firmware values. Both boards confirmed working by the student.
- Step 2 (through the app, Settings: slcan, COM port, 500000): 16,304 frames in about 8 min,
  then one malformed serial line ("non-hexadecimal number found in fromhex()") killed the
  session. Fix: `can_interface.py` skips ValueError lines. Afterwards: 1,188 frames in 21 s,
  stable at 2,421 frames (about 55/s).
- Stale data after unplugging (found 2026-09-13): status only changed on a hard error, buffers
  never cleared. Fix: `_STALE_AFTER_SECONDS = 5.0`, buffers cleared on disconnect, `live_mode`
  (hardware/simulator) read by the client (`VehicleSnapshot.LiveMode`).
- No alert on 0x666 was seen through the app. The 12 Sept explanation (30 s whitelist window)
  was WRONG: the whitelist is offline only (server.py analyze); live capture had no identifier
  check at all, and the rig was connected as nissan_leaf, so 0x316/0x3F9 were not DBC-decoded and
  /api/live/decoded-signals read them with the cross-vehicle signal_map (Hyundai EMS11, ECS12).
- Fixed 2026-09-28: profile `bench_rig` (vehicle_profiles.py, `complete_dbc=True`) with
  `assets/dbc_files/bench-rig.dbc` (0x316 Vehicle_Speed km/h, 0x3F9 State_Of_Charge %, 0x666 left
  out on purpose). It scores with the general model (model_status alias). can_interface.py: for a
  complete-DBC profile, an identifier outside the DBC raises an alert (layer whitelist, attack_type
  unknown_identifier, score max(fused, 0.95), 1 s cooldown per ID). server.py
  /api/live/decoded-signals uses the frame's profile decoding before signal_map. Tests:
  backend/tests/test_bench_rig_profile.py (9, virtual bus). NOT yet re-run on the physical rig,
  and the on-screen display has not been click-tested.
- Test was made with the first pipeline, before clean-2 promotion; not repeated with final models.

## 4. Decisions (student, 2026-09-27)
- Chapter 5 tells both: the first pipeline and its six fixes as iteration 1, the
  clean-2 rebuild and holdout results as the final validation.
- Voice: "we", except the Scrum part (Ch. 1, section 1.6 Development methodology), which
  uses "I" because the student worked alone on the project (student, 2026-09-28).
- Live hardware (updated 2026-09-28): both Arduino boards were tested; see the bench rig
  facts in section 3. Claim nothing beyond them.
- Report structure: one paragraph per chapter (student, 2026-09-28).

## 5. Open questions for the student
- Live hardware: which parts of the bench rig path were tested (flashing, serial
  link, slcan bridge, frames reaching the app, live scoring)?
- Anything in Chapter 1 about Capgemini, the team and the internship period that
  must be checked (dates, team name, supervisor roles).

## 6. State at the end of 2026-09-27
- Every chapter, the front matter and the appendices are rewritten. The thesis builds
  (99 pages) with no error, no undefined reference and no overfull line above 10 pt.
- Style audit (scratchpad script thesis_audit.py): 0 dash punctuation in all files. The
  only " - " left is the academic year on the official ESPRIT cover ("2025 - 2026").
- Screenshots of Ch. 4 and App. D were captured from the final application on the
  Jaguar I-PACE holdout (images/screenshots/f01 ... f10). The old screenshots (01_ ... 10_)
  are no longer used by the report and can be deleted.

## 7. Still to do (needs the student)
1. DONE 2026-10-02: Gantt rebuilt on real months. Internship February to July 2026 (student). Dated evidence: milestones finished in June (notes 06-11 to 06-22), fixes 07-05, bench rig 08-16 and 09-12, model rebuild 09-23/24, report from 09-27. Bars before June are estimates.

## 8. Done on 2026-09-28
- Acknowledgements: thanks to Nadia Boulifa (ESPRIT), Hamda Guizani (Capgemini BMS team),
  the Automotive division of Capgemini Tunisia, and the jury. Cover year now "2025/2026".
- All 22 diagrams redrawn in PlantUML (`thesis/diagrams/*.puml`, shared `style.iuml`:
  monochrome, Arial, no shadows, plain UML). Real class, method, endpoint and file names.
  Each one checked against the code. Fixes found on the way: the explanation lookup
  falls back to the live buffer and only returns 404 when it is empty; only Gemini gets
  the web results; only Gemini and Ollama answers go through the number check.
- Figure sizes set so that diagram text prints at about 6 to 8 pt; tall diagrams are
  capped by height (0.78 to 0.8 of the text height).
- Ch. 3 and Ch. 4 explanation engine text now lists six context sources (signal map and
  web search added), the number check and the engine name shown on screen. NVD acronym added.
- SUPERSEDED the same day (student: "should look like I made them with Lucidchart or a widely
  used tool"): all 22 figures are now real draw.io files, pastel draw.io palette. Sources:
  `thesis/drawio/*.drawio` (editable in draw.io desktop, installed with winget JGraph.Draw),
  built by `thesis/drawio/figures.py` (shapes in `dio.py`); `python figures.py [name]` exports
  each PNG with draw.io and copies it to `thesis/diagrams/`, where the report reads it.
  Same verified content as the PlantUML versions. The old `thesis/diagrams/*.puml` files and
  `style.iuml` are no longer used. Figure sizes set from the real proportions (text 6.0 to
  9.0 pt printed; class diagram and training pipeline are the densest at 6.0 pt).
- Build: 103 pages, no errors, no undefined references, only three overflows under 1 pt
  (appendix tables).
- Hardware (2026-09-28): the student confirmed that both Arduino boards were tested. Every
  "partly tested" passage now says "tested on a bench rig, not on a vehicle", and Ch. 5 has a
  new section, Live capture on the bench rig (sec:validation-bench), with the facts above and
  its limits. Build: 104 pages, clean.

## 9. Jury-proofing pass (2026-09-28, student's brief)
- Scrum section is now "iterative approach inspired by Agile principles" (still in "I"); the
  Scrum cycle figure was removed from the report (drawio/scrum_workflow.drawio kept).
- ML parameters (200 trees, seed 42, window 10, warmup 10, 1,000 rows, exact quantile rule)
  moved to Appendix B, table tab:app-model-params. Main text keeps the method and the 2%.
- Explanation engine rewritten as a supporting feature: never changes a score, flag or
  severity. Context sources, web search (Wikipedia, NVD), cosine similarity and the cache are
  in Appendix B only. ai_workflow figure simplified; sequence_explain labels generalised.
- Offline vs runtime wording: they share features and models, not alert rules. Never write
  "same detection engine" for offline analysis. Simulation and live capture use no file parser.
- "Software readiness" is now "Stability within the validated scope" (no certification claim).
- Removed: endpoint count from Ch. 3 and the repository figure, HTTP 409, polling periods,
  lock and thread details, signal discovery thresholds.
- Live path speed in Ch. 3 aligned with Ch. 5 (200 to 260 frames/s, 24 ms per call). The old
  "115" and "42 ms" came from a run made alongside an offline analysis.
- Bibliography 11 -> 26 entries, each checked online: Koscher 2010, Checkoway 2011, Miller and
  Valasek 2015, Lokman 2019, Muter and Asaj 2011, Song 2016, Cho and Shin 2016, Scholkopf
  2001, Breunig 2000, Ester 1996, CANoe, SavvyCAN, can-utils, python-can, CSS EV Data Pack,
  EV-CANlogs. Every entry is cited.
- Final verification (2026-09-28): the offline analysis also accepts the general model (first
  design) for vehicles without their own model; the Settings alert threshold (0.55) is stored by
  the client only and never applied to scoring (runtime uses 0.40); the model selector lists 20
  entries (general + 14 vehicle models + 5 DBC profiles incl. bench_rig). Text corrected.

## 10. Final cleanup pass (2026-09-28): 107 -> 92 pages
- Cover: "2025 - 2026" (template text, dash allowed), template sans font (phv), subtitle line,
  "Prepared by / Academic Supervisor: Mrs Nadia Boulifa / Corporate Internship Supervisor: Mr Hamda
  Guizani", vector Capgemini Engineering logo (fr.wikipedia Capgemini_Engineering.svg, cropped,
  images/cover_capgemini_engineering.pdf) centred in the dotted box (9.83-17.01 x 23.47-26.13 cm).
- Added: Dedication (00_dedication.tex, people from the student's own acknowledgements only);
  Table 2.1 existing solutions vs CANvisionNative; "Project contributions" in the conclusion.
- Removed figures: rest_api_flow, feature_engineering, runtime_inference, ai_workflow,
  validation_workflow, mf4_workflow, bugfix_timeline, export_workflow, repo_structure,
  f04_diagnostics, f05_settings, fusion histogram; tab:final-model; Appendix E (merged in C);
  App. B dependencies/startup/saved config; App. D severity/layer tables; Ch. 5 Future
  improvements (kept in the general conclusion); Ch. 4 Charts section; repository audit.
- FIXED A WRONG FIGURE: before/after throughput chart said 286 fps; the saved report says 194.6.
  New charts from the table numbers: images/graphs/before_after_summary.png and
  alert_breakdown.png (scripts next to them).
- Client display labels: offline CRITICAL/HIGH/WARNING are shown as CRITICAL/WARNING/INFO in
  the desktop alert lists (HomeViewModel.cs). Documented in App. B and Ch. 4.
- Tables: prose columns ragged right (P{}/Y column types in config.tex). \bibitemsep 3pt.

## 11. Restructure (2026-09-30): 92 -> 72 pages, bibliography last
- Appendices removed from main.tex (files kept on disk, not compiled). Essentials moved into
  chapters: Table 3.1 two detection paths (fusion weights, alert rules, both severity scales,
  client labels INFO/WARNING/CRITICAL), Table 3.3 dataset files + Section 3.6.2 "Dataset files"
  (sec:datasets) with source logos, Table 3.5 model parameters (200 trees, seed 42, window 10...).
- Offline merge rule corrected: MORE than eight alerts on one ID within 2 s (dedup.py count > 8).
- New logos (simple-icons / Wikimedia / vendor sites) in images/logos: pandas, numpy, pytest,
  arduino, github, drawio, latex, css_electronics, ornl, korea_university. Capgemini logo in Ch1.
- Ch4 reordered like the reference thesis: environment, backend, user interface (all screens +
  PDF report and CSV export figures). Desktop tests now 86 (PDF report tests added).
- Body text ~17,000 words (was ~20,900 incl. appendices).
