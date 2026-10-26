# CANvisionNative: defense speech

About 13 minutes of talk plus the 3 min 46 s demo video, which you narrate live, so about 17 minutes in total (limit: 20).
**[CLICK]** means press the clicker. Speak slowly and pause after every number.

---

**Slide 1: Title**
Good morning, members of the jury. My name is Mohamed Mootaz Ben Kraiem. Today I present CANvisionNative, a diagnostic and validation platform for the CAN traffic of Battery Management Systems. I built it at Capgemini Engineering, under the supervision of Mrs Nadia Boulifa and Mr Hamda Guizani.

**Slide 2: Summary**
My presentation has eight parts. I start with the context and the problem. Then I present the objectives, the way I organised my work, and the requirements. Then comes the solution, followed by a short demonstration of the real application. I finish with the validation, the limits and the conclusion.

**Slide 3**
First, the host company.

**Slide 4: Capgemini Engineering**
I am not an intern. I follow a work and study program at Capgemini Engineering. Since September 2024, I have worked full time, from nine to six, five days a week, as a QA tester of BMS software for BMW Group, in the Battery Management Systems team of the Automotive division in Tunisia. I study at ESPRIT on Saturdays.
A big part of my daily work is checking CAN messages: is a cell voltage, a temperature or a state of charge sent at the right rate, and with a plausible value? CANvisionNative was not a team deliverable. I started it in February 2026, alongside my job, and the idea came from the difficulties of this daily work.

**Slide 5**
To follow the rest of the presentation, we need one idea: how the computers inside a car talk to each other.

**Slide 6: The CAN bus**
A car contains many small computers called ECUs: the battery management system, the motor controller, the brakes, the dashboard and others. They all share one bus made of two wires, CAN high and CAN low.
Here, the BMS sends a frame with the identifier 0x3F9. The frame travels in both directions, and every node receives it. Nobody sends a frame to one specific receiver. Each node reads the identifier and decides if the frame interests it.

**Slide 7: The CAN frame**
A frame carries an identifier, a length, up to eight bytes of data and an error check. Here is the BMS sending its frame.
**[CLICK]** Now an unknown device sends exactly the same frame: the same identifier and the same bytes. For every receiver, the two frames are identical.
**[CLICK]** This is because a CAN frame has no sender identity, no authentication and no encryption. So the bus cannot tell a genuine frame from a forged one, or from a faulty one.

**Slide 8**
So, what problems did the project start from?

**Slide 9: Open issues**
I present them as the open issues of daily BMS validation work.
**[CLICK]** First, there is no live view. Raw frames tell us what happened, not whether it should have happened.
**[CLICK]** Second, replay is weak. Tools replay the frames, but they do not judge them.
**[CLICK]** Third, the tools are scattered. One investigation needs an analyser, a scanner and a spreadsheet.
**[CLICK]** Fourth, alerts come without an explanation: just a number, with no cause.
**[CLICK]** And underneath all this, CAN has no security. It is a real motivation, but a secondary one in this project.

**Slide 10**
What already exists?

**Slide 11: Existing tools**
There are four families of tools. CAN analysers, such as Vector CANoe, capture and replay traffic, but they do not judge what is normal for a given vehicle. Intrusion detection research learns normal traffic, but its models rarely transfer to another vehicle, and they do not explain their alerts. Viewers and diagnostic scanners only see part of the picture. Each tool covers one part of the problem; none of them puts everything in one workflow.

**Slide 12: Problem statement**
This leads to my problem statement: how can we give a BMS engineer one view of the CAN traffic, adapted to each vehicle, that explains its own alerts, and prove that it works on real recordings?

**Slide 13**
Each part of this question answers a problem we just saw. "One view" answers the missing live view, the weak replay and the scattered tools. "Adapted to each vehicle" answers the models that rarely transfer from one car to another. And "explains its own alerts" answers the bare numbers.

**Slide 14: The idea**
My answer is CANvisionNative: one platform where the engineer replays, monitors and understands the traffic of a vehicle. One view instead of scattered tools, models adapted to each vehicle, and alerts that explain themselves.

**Slide 15**
What are the objectives of the project?

**Slide 16: Objectives**
The general objective is to design, build and validate a diagnostic platform for Battery Management Systems: one view of the CAN traffic, adapted to the vehicle, that explains its own alerts.
It has six specific objectives. First, a detection pipeline that combines a machine learning model with timing, payload and persistence checks. Second, the common log formats, a live simulator and live capture. Third, one model per vehicle, and in production only the models evaluated on a recording they never saw. Fourth, a desktop client to import a log, replay it, review the anomalies and export a report. Fifth, an explanation layer, separate from detection. And sixth, a validation on real recordings, with every defect corrected.

**Slide 17: Methodology**
How did I organise the work? I followed the Unified Process, in four phases.
In inception, in February, I defined the vision, the use cases, the risks and the plan. In elaboration, milestone M1 built the executable architecture: the client, the backend, and one runtime engine for replay, simulation and live capture.
Construction took four iterations: first, the first pipeline and the client, milestones M3 to M8; second, its validation on a Kia EV6 recording, with six corrections; third, the hardware layer and the bench rig, milestone M2; and fourth, the rebuild of the models, evaluated on recordings they never saw. Transition delivered the final release, the tests, the deployment guide and the report.
I chose the Unified Process because it is driven by use cases and by risks, centred on the architecture, and iterative: two things were unknown at the start, how well a model would generalise and how many defects validation would find. Waterfall would have frozen the design too early, and Scrum assumes a team. The work started with inception, so the next step is the requirements.

**Slide 18**
The inception phase captured the requirements. So, what must the platform do?

**Slide 19**
First, it must import a recorded log in the formats engineers use: CSV, MF4, Vector, candump and PCAN. The engineer then chooses the vehicle, so that its own models and its own DBC file are used.

**Slide 20**
Then it must replay the log and detect anomalies. When it cannot judge a frame, it must say so instead of hiding it. And it must explain any alert in plain language.

**Slide 21**
Finally, it must work live, with a simulator or a real CAN adapter, and export the results as a CSV file and a PDF report.

**Slide 22**
Now, the solution.

**Slide 23: Architecture**
Let me build the architecture in the order the data flows. It starts with the traffic sources: recorded logs, a simulator or a CAN adapter.
**[CLICK]** The parser turns every format into the same stream of frames, and decodes the signals with the DBC file.
**[CLICK]** For each identifier, we compute nine features over the last ten frames.
**[CLICK]** The detection engine scores each frame with the Isolation Forest of its identifier, plus timing, payload and persistence rules.
**[CLICK]** A FastAPI backend serves the results and the explanations.
**[CLICK]** And the WPF client shows everything and exports the reports.
**[CLICK]** So we have two programs on one machine, talking over HTTP.

**Slide 24: Detection pipeline**
Here is how one frame is judged, during replay or live capture. We compute its features, and the Isolation Forest of its identifier gives a model score. Then four layers are fused: timing, payload, the model and persistence. If the fused score reaches 0.40, an alert is raised.
**[CLICK]** A normal frame scores low, here 0.17, so nothing happens.
**[CLICK]** An unusual frame scores high, here 0.82, so we get an alert with severity HIGH. These two scores are examples.
And a frame that no model can judge is reported as unresolved. It is never counted as normal.

**Slide 25: Isolation Forest**
Now, inside the model. **[CLICK]** Each grey point is a normal frame of one identifier; the red point is unusual. An Isolation Forest cuts the space at random. After only two cuts, the red point is already alone, while a normal point needs many more cuts. Few cuts means a high anomaly score. The threshold is set so that two percent of the training rows pass it.

**Slide 26: One model per vehicle**
Why one model per vehicle? Here are identifiers of the Kia EV6. Each one has its own Isolation Forest: 161 models in total.
**[CLICK]** The Jaguar I-PACE has a different set: 46 models.
**[CLICK]** Even the same identifier, 0x36, carries different traffic on each car: different training rows and different features, so two different models.
**[CLICK]** CAN traffic depends on the vehicle, so the models must be vehicle specific.

**Slide 27: Explanation**
The explanation always starts from an alert raised by the detection engine. Here it is identifier 0x063, with a score of 0.535.
**[CLICK]** The backend gathers the context of the alert and asks Gemini. If Gemini does not answer, it asks a local Ollama model, and if neither answers, it writes a rule based text. The result is a diagnosis: the dominant signal, the likely cause and what to check.
**[CLICK]** Here it is in the application.
**[CLICK]** And this is the rule of the system: the AI explains, the detection engine decides. The explanation never changes a score, a flag or a severity.

**Slide 28**
Can we see it working? Let me show you the real application.

**Slide 29: Demo** (click on the video to play it; Space pauses it)
The video lasts 3 min 46 s and is silent: you say these words live. Each block starts when its screen appears (video times in brackets). The video leaves a little time at the end of each block, so take your time.
- (0:00, opening) Everything you will see now is the real application, running on a real recording. And one detail matters: the model never saw this file during training. What you see is the model meeting this traffic for the first time.
- (0:17, Home) CANvisionNative opens on one choice: a live session on the bus, or an offline import of a recording. The live session stays locked until the backend runs and an adapter is plugged in. We start offline.
- (0:34, Import) I import a recording of a Jaguar I-PACE: 50,361 frames, kept out of training on purpose.
- (0:45, Vehicle model) I choose the Jaguar model. Its status is shown before anything runs: evaluated on a holdout recording. A model that failed this test would be refused.
- (0:58, Analysis) Now every frame is scored by the Isolation Forest of its own CAN identifier. The video speeds this part up; in the application it takes about a minute.
- (1:11, Dashboard) Here is the result. 40,477 frames could be scored, and 1,249 of them are flagged: about 3 percent, close to the 2 percent the model was calibrated on. The frames that no model can judge are not hidden: they are counted as unresolved, with their reason. And the dataset card confirms it: this is a test file the model never saw.
- (1:40, Log Playback) In Log Playback, the recording plays back. The marked spans on the timeline show where the flagged frames are, and the chart shows each score against the threshold of the model.
- (1:53, Telemetry) Telemetry shows the channels. The Jaguar has no DBC file, so the system does not invent a meaning: the channels stay raw bytes, clearly marked as undecoded.
- (2:07, Diagnostics) Diagnostics shows the health of the adapter and the IDS event log.
- (2:14, Anomaly Intel) Anomaly Intel groups the 1,249 flagged frames into 339 alerts, each with the layers that raised it. I select one and ask for an explanation. Gemini writes it: the dominant signal, the likely cause, and what to check. But remember the rule: AI explains, the detection engine decides. The explanation never changes a score.
- (2:44, Export) One click exports the evidence: a CSV file, and a PDF report with the session, the model and its status, the scores, and every alert with its explanation.
- (2:57, Settings) In Settings: the hardware interface, the Gemini key, and the DBC profile of each vehicle.
- (3:06, Tesla Model 3) Last recording: the battery of a Tesla Model 3. This one has a DBC file, so watch the bytes become real battery signals. State of charge: 19.2 percent. Battery voltage: 337 volts. Cell voltages: around 3.5 volts. That is exactly what a BMS engineer checks every day. There is no validated Tesla model yet, so here the general model scores the frames.
- (live hardware part: added this evening)
- (3:35, closing) From raw CAN frames to scored frames, explained alerts and a report, in one tool. That was the real application.

**Slide 30**
How do we know it works? Validation was done in two of the four iterations, the second and the fourth, with one rule: evidence before any change, and never tuning a threshold to make the numbers look better.

**Slide 31: Iteration 2, validation**
In iteration 2, I ran the first pipeline on a one hour Kia EV6 recording. It produced 15,945 alerts, 16 percent of the frames. Instead of raising the threshold, we attributed every alert to the layer that dominated it.
**[CLICK]** This revealed six silent defects. None of them crashed the program. For example, the selected vehicle model was never used, and the car was seen as parked during an hour of driving.

**Slide 32: Corrections**
After the corrections, on the same recording and with the same threshold, the alerts dropped to 11,971, about a quarter less, and the saturated model scores disappeared. The threshold was never touched.
But the design was still fragile, so in iteration 4 I rebuilt every model with a stricter pipeline, where each model is evaluated on a recording it never saw before it can enter production.

**Slide 33: Iteration 4, final models**
That is iteration 4. The four final models flag between 0.6 and 6 percent of frames they never saw, which is close to the 2 percent of their calibration. ROAD is higher, because one identifier never changes in training but changes on the highway. The MG ZS EV model failed this test, so it was held back. These recordings have no attack labels, so these numbers are flagged rates, not detection rates.

**Slide 34**
Now the limits, stated plainly.

**Slide 35: Limits**
There are four limits. First, live capture was tested on a bench rig, not on a real vehicle. Second, the live path scores about 200 to 260 frames per second: enough for a slow bus, but not for a busy one. Third, the test data has no attack labels, so we report flagged rates only. And fourth, some identifiers are too rare to get their own model. Each of these limits is measured and stated in the report.

**Slide 36**
To conclude.

**Slide 37: Conclusion**
The project delivered a client and a backend that work on recorded logs, on a simulator and on live capture; four vehicle models evaluated on more than a million unseen frames; a pipeline that refuses weak models; explanations in plain language; a bench rig; and two test suites.
The main lesson I take from this project is that a detection system is only as trustworthy as the evidence behind each of its numbers.

**Slide 38: Next steps**
For the next steps: validate live capture on a real vehicle, evaluate the models on recordings with labelled attacks, make the live path fast enough for busy buses, and collect more recordings for each vehicle.

**Slide 39: Closing**
CANvisionNative: from CAN frames to explainable diagnostics. **[CLICK]** Thank you for your attention, and thank you to my supervisors, Mrs Nadia Boulifa and Mr Hamda Guizani, for their support. I am ready for your questions.
