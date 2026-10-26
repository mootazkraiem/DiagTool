# CANvisionNative — Presenter Cue Script

**Target:** about 13 minutes of speaking + 3:36 demo = about 17 minutes. Speak slowly; pause after numbers.

**Controls:** `[NEXT]` = advance to the next slide. `[CLICK]` = click within the current slide. During slide 29, play the video and follow its timestamps; the demo is silent, so narrate live.

## Opening and context

**1 — Title**  Good morning, members of the jury. I’m Mohamed Mootaz Ben Kraiem. I’ll present CANvisionNative, a diagnostic and validation platform for BMS CAN traffic, built at Capgemini Engineering with Mrs Nadia Boulifa and Mr Hamda Guizani. **[NEXT]**

**2 — Summary**  I’ll cover context, objectives, method, requirements, the solution, a live-narrated demo, validation, limits and conclusion. **[NEXT]**

**3 — Host company**  First, the host company. **[NEXT]**

**4 — Capgemini Engineering**  I’m in a work-study program, not an internship. Since September 2024 I’ve worked full time as a BMS software QA tester for BMW Group in Tunisia, while studying at ESPRIT on Saturdays. Daily CAN checks inspired this personal project, started in February 2026 alongside my job. **[NEXT]**

**5 — Transition**  To follow the project, first we need to understand how computers in a car communicate. **[NEXT]**

**6 — CAN bus**  ECUs share a two-wire bus. The BMS sends identifier 0x3F9; every node receives the frame and decides from the identifier whether it is relevant. There is no addressed receiver. **[NEXT]**

**7 — CAN frame**  A frame carries an identifier, length, up to eight data bytes and an error check. **[CLICK]** An unknown device can send the same identifier and bytes, so receivers cannot distinguish it. **[CLICK]** CAN has no sender identity, authentication or encryption; a genuine, forged or faulty frame can look the same. **[NEXT]**

## Problem and objectives

**8 — Transition**  So, what problems did the project start from? **[NEXT]**

**9 — Open issues**  **[CLICK]** No live view: raw frames show what happened, not whether it should. **[CLICK]** Replay tools replay but don’t judge. **[CLICK]** Tools are scattered across analyzers, scanners and spreadsheets. **[CLICK]** Alerts give a number without a cause. **[CLICK]** CAN security motivates the work, but is secondary here. **[NEXT]**

**10 — Transition**  What tools already exist? **[NEXT]**

**11 — Existing tools**  Analyzers capture and replay but don’t judge vehicle-specific normality. IDS research models rarely transfer and often cannot explain alerts. Viewers and scanners show only part of the picture. No single tool joins the workflow. **[NEXT]**

**12 — Problem statement**  How can we give a BMS engineer one view of CAN traffic, adapted to each vehicle, with explanations for alerts, validated on real recordings? **[NEXT]**

**13 — Unpacking the question**  “One view” addresses missing live visibility, weak replay and scattered tools. “Adapted to each vehicle” addresses poor model transfer. “Explains its alerts” addresses bare numbers. **[NEXT]**

**14 — The idea**  CANvisionNative lets an engineer replay, monitor and understand a vehicle’s traffic in one platform, with vehicle-specific models and explainable alerts. **[NEXT]**

**15 — Transition**  What were the project objectives? **[NEXT]**

**16 — Objectives**  The goal: build and validate a BMS diagnostic platform. Specifically: combine ML with timing, payload and persistence checks; support common logs, simulation and live capture; use vehicle-specific models evaluated on unseen recordings; import, replay, review and export from a desktop client; explain alerts separately from detection; validate on real data and correct defects. **[NEXT]**

**17 — Methodology**  I used the Unified Process. Inception defined vision, use cases, risks and plan. Elaboration established the client, backend and shared runtime. Construction iterated on the pipeline, Kia validation and six fixes, hardware bench, and model rebuild with unseen-recording evaluation. Transition delivered release, tests, deployment guide and report. Iteration and risk focus suited the unknown generalization and defect count; Waterfall would freeze too early, and Scrum assumes a team. **[NEXT]**

## Requirements and solution

**18 — Requirements transition**  Inception captured what the platform must do. **[NEXT]**

**19 — Import**  Import CSV, MF4, Vector, candump or PCAN logs, then select a vehicle to load its own models and DBC. **[NEXT]**

**20 — Analyze**  Replay and detect anomalies; report frames the system cannot judge as unresolved; explain alerts in plain language. **[NEXT]**

**21 — Live and export**  Support simulator or real adapter, and export CSV results and a PDF report. **[NEXT]**

**22 — Transition**  Now, the solution. **[NEXT]**

**23 — Architecture**  Follow the data: traffic sources. **[CLICK]** Parser normalizes frames and decodes signals with DBC. **[CLICK]** Nine features are computed over the last ten frames for each identifier. **[CLICK]** The identifier’s Isolation Forest combines with timing, payload and persistence rules. **[CLICK]** FastAPI serves results and explanations. **[CLICK]** WPF displays and exports them. **[CLICK]** Two programs run on one machine and communicate over HTTP. **[NEXT]**

**24 — Detection pipeline**  Each frame gets features and a score from its identifier’s Isolation Forest; timing, payload, model and persistence are fused. At 0.40, an alert is raised. **[CLICK]** Normal example: 0.17, no alert. **[CLICK]** Unusual example: 0.82, HIGH severity. These are examples. Unjudgeable frames are unresolved, never normal. **[NEXT]**

**25 — Isolation Forest**  **[CLICK]** The model randomly cuts feature space. The unusual red point is isolated in few cuts; normal points take more. Fewer cuts mean a higher anomaly score. Threshold calibration lets two percent of training rows pass it. **[NEXT]**

**26 — Vehicle-specific models**  Kia EV6 has 161 identifier models. **[CLICK]** Jaguar I-PACE has 46. **[CLICK]** Even identifier 0x36 carries different traffic in each car and uses different training data. Vehicle traffic differs, so models are vehicle-specific. **[NEXT]**

**27 — Explanation**  Explanation starts from a detection alert: identifier 0x063, score 0.535. **[CLICK]** Backend gathers context and asks Gemini, then local Ollama, then uses rule-based text if needed. It gives the dominant signal, likely cause and checks. **[CLICK]** Here is the app view. **[CLICK]** AI explains; detection decides. Explanation never changes score, flag or severity. **[NEXT]**

## Demonstration — slide 29, 3:36

Click the video to play; Space pauses. Narrate each section as its screen appears. The video leaves a little time at each transition.

- **0:00 — Opening:** This is the real application on a real recording. The model never saw this file in training; this is its first encounter with this traffic.
- **0:17 — Home:** Choose live bus session or offline recording. Live is locked until backend and adapter are ready; we’ll start offline.
- **0:33 — Import:** Jaguar I-PACE recording: 50,361 frames, deliberately held out of training.
- **0:43 — Vehicle model:** Select Jaguar. Its holdout evaluation status appears before analysis; a model that failed would be refused.
- **0:56 — Analysis:** Each frame is scored by the Isolation Forest for its CAN identifier. The video speeds this up; the app takes about a minute.
- **1:08 — Dashboard:** 40,477 frames scored; 1,249 flagged, about 3%, close to the calibrated 2%. Unjudgeable frames remain visible as unresolved with reasons. The dataset card confirms this was unseen test data.
- **1:37 — Log Playback:** Timeline marks flagged spans; chart compares each score with the model threshold.
- **1:49 — Telemetry:** Jaguar has no DBC, so channels stay raw bytes and are clearly marked undecoded.
- **2:02 — Diagnostics:** Adapter health and IDS event log.
- **2:09 — Anomaly Intel:** 1,249 flagged frames are grouped into 339 alerts with their contributing layers. Select one for Gemini’s likely cause and checks. AI explains; detection decides.
- **2:37 — Export:** One click exports CSV and a PDF with session, model status, scores, alerts and explanations.
- **2:50 — Settings:** Hardware interface, Gemini key and each vehicle’s DBC profile.
- **2:58 — Tesla Model 3:** This battery recording has a DBC, so bytes decode into signals: 19.2% state of charge, 337 V, cell voltages around 3.5 V. No validated Tesla model yet, so the general model scores these frames.
- **Live hardware segment:** Narrate what is visible in the added segment.
- **3:27 — Closing:** From raw CAN frames to scored frames, explained alerts and a report in one tool. That is the real application.

## Validation and close

**30 — Validation transition**  How do we know it works? I validated in iterations two and four: evidence before changes, and no threshold tuning to improve the numbers. **[NEXT]**

**31 — Iteration 2**  On a one-hour Kia EV6 recording, the first pipeline produced 15,945 alerts: 16% of frames. We attributed alerts to their dominant layer instead of raising the threshold. This exposed six silent defects, including not using the selected vehicle model and treating an hour of driving as parked. **[NEXT]**

**32 — Corrections**  With the same recording and threshold, corrections reduced alerts to 11,971, about a quarter fewer, and removed saturated model scores. The threshold did not change. Iteration 4 rebuilt models with an unseen-recording evaluation gate. **[NEXT]**

**33 — Final models**  Four final models flagged 0.6–6% of unseen frames, around the 2% calibration rate. ROAD is higher because one identifier changes on the highway but never changed in training. MG ZS EV failed and was held back. No attack labels exist, so these are flagged rates, not detection rates. **[NEXT]**

**34 — Limits transition**  Now, the limits, stated plainly. **[NEXT]**

**35 — Limits**  Live capture was tested on a bench, not a real vehicle. Live throughput is about 200–260 frames per second, enough for a slow bus but not a busy one. Tests lack attack labels, so only flagged rates are reported. Rare identifiers may lack their own model. These limits are measured in the report. **[NEXT]**

**36 — Conclusion transition**  To conclude. **[NEXT]**

**37 — Conclusion**  Delivered: client and backend for logs, simulation and live capture; four vehicle models evaluated on over a million unseen frames; a pipeline that rejects weak models; plain-language explanations; bench rig and two test suites. The lesson: a detection system is only as trustworthy as the evidence behind its numbers. **[NEXT]**

**38 — Next steps**  Validate live capture in a real vehicle; test on recordings with labelled attacks; speed up the live path for busy buses; collect more recordings per vehicle. **[NEXT]**

**39 — Closing**  CANvisionNative: from CAN frames to explainable diagnostics. **[CLICK]** Thank you for your attention, and thank you to my supervisors, Mrs Nadia Boulifa and Mr Hamda Guizani. I’m ready for your questions.
