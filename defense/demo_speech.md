# Demo speech (to record, then the video is cut to your timing)

How to record:
- Read the speech at the pace you will use at the defense.
- Do not read the block numbers or titles aloud. They are only there to help you.
- Leave a clear pause of about 2 seconds between blocks.
- If you make a mistake, stop, wait 3 seconds, and start that block again. I will keep the last version.

---

**1. Opening**
Everything you will see now is the real application, running on a real recording. And one detail matters: the model never saw this file during training. What you see is the model meeting this traffic for the first time.

**2. Home**
CANvisionNative opens on one choice: a live session on the bus, or an offline import of a recording. The live session stays locked until the backend runs and an adapter is plugged in. We start offline.

**3. Import**
I import a recording of a Jaguar I-PACE: 50,361 frames, kept out of training on purpose.

**4. Vehicle model**
I choose the Jaguar model. Its status is shown before anything runs: evaluated on a holdout recording. A model that failed this test would be refused.

**5. Analysis**
Now every frame is scored by the Isolation Forest of its own CAN identifier. The video speeds this part up; in the application it takes about a minute.

**6. Dashboard**
Here is the result. 40,477 frames could be scored, and 1,249 of them are flagged: about 3 percent, close to the 2 percent the model was calibrated on. The frames that no model can judge are not hidden: they are counted as unresolved, with their reason. And the dataset card confirms it: this is a test file the model never saw.

**7. Replay**
In Log Playback, the recording plays back. The marked spans on the timeline show where the flagged frames are, and the chart shows each score against the threshold of the model.

**8. Telemetry**
Telemetry shows the channels. The Jaguar has no DBC file, so the system does not invent a meaning: the channels stay raw bytes, clearly marked as undecoded.

**9. Diagnostics**
Diagnostics shows the health of the adapter and the IDS event log.

**10. Anomaly Intel**
Anomaly Intel groups the 1,249 flagged frames into 339 alerts, each with the layers that raised it. I select one and ask for an explanation. Gemini writes it: the dominant signal, the likely cause, and what to check. But remember the rule: AI explains, the detection engine decides. The explanation never changes a score.

**11. Export**
One click exports the evidence: a CSV file, and a PDF report with the session, the model and its status, the scores, and every alert with its explanation.

**12. Settings**
In Settings: the hardware interface, the Gemini key, and the DBC profile of each vehicle.

**13. Tesla Model 3**
Last recording: the battery of a Tesla Model 3. This one has a DBC file, so watch the bytes become real battery signals. State of charge: 19.2 percent. Battery voltage: 337 volts. Cell voltages: around 3.5 volts. That is exactly what a BMS engineer checks every day. There is no validated Tesla model yet, so here the general model scores the frames.

**14. Live hardware (added this evening)**
So far, recorded files. Now the same engine, on a real CAN bus.
[The rest of this block is written after the hardware recording, from what it actually shows.]

**15. Closing**
From raw CAN frames to scored frames, explained alerts and a report, in one tool. That was the real application.
