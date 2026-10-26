# Meeting with my academic supervisor

About 5 minutes of talk, then her questions. Have the final deck, the thesis PDF and the demo video open before you start.

---

**1. Opening**
Good morning, Mrs Boulifa, and thank you for your time. Today I would like to show you where CANvisionNative stands before the defense: the thesis, the presentation and the demo. Then I would really value your opinion on a few points.

**2. The project in one minute**
As a reminder, CANvisionNative is a platform for the CAN traffic of Battery Management Systems. The engineer imports a recording or connects live, chooses the vehicle, and the platform scores every frame with a model trained for that vehicle. When something is unusual, it raises an alert and explains it in plain language. The rule of the system is simple: the AI explains, the detection engine decides.

**3. What I have done**
First, the thesis is complete: 73 pages. I also corrected the description of my situation. I am not an intern: I have followed a work and study program at Capgemini Engineering since September 2024, as a QA tester of BMS software for BMW Group, and I started this project in February 2026, alongside my job. The thesis now says this clearly.

Second, the presentation. *[open the deck]* It follows eight parts: context, problem, requirements, solution, demo, validation, limits and conclusion. The talk takes about twelve minutes, plus a demo of under three minutes, so it stays well within the twenty minutes. I also kept five hidden backup slides for questions, and a PDF copy in case the projector computer has a problem.

Third, the demo. *[go to slide 27 and play the video]* I recorded the real application. It imports the Jaguar I-PACE test recording, a file the model never saw during training, analyses it, replays it, opens an alert with its explanation, and exports the PDF report. The last part uses a Tesla Model 3 recording that has a DBC file, so you can see the raw bytes turn into battery signals, such as the state of charge and the cell voltages. While preparing this demo, I also found and fixed a bug: the signal monitor stayed empty for recorded files, even when a DBC file was available.

**4. The results**
The validation took two iterations. In the first one, the first version raised 15,945 alerts on a one hour Kia EV6 recording. Instead of raising the threshold, I traced every alert to its cause, and this revealed six silent defects. After the corrections, with the same threshold, the alerts dropped to 11,971.
In the second iteration, I rebuilt every model with a stricter pipeline, where each model is tested on a recording it never saw. The four final models flag between 0.6 and 6 percent of new frames, close to the 2 percent they were calibrated for. The MG ZS EV model failed this test, so I held it back.

**5. The limits**
I state the limits openly. Live capture was tested on a bench rig, not on a real car. The live path handles about 200 to 260 frames per second, which is not enough for a busy bus. And the test recordings have no attack labels, so I report flagged rates, not detection rates.

**6. What I would like your opinion on**
- Is the balance between the talk and the demo right, or should I shorten something?
- The demo uses a normal recording, so it shows flagged frames but no real attack. Should I add an attack example, or is it enough to explain clearly what the flagged rate means?
- Is there anything in the thesis you would like me to change before I submit the final version?
- Which questions do you expect from the jury, so that I can prepare for them?

**7. Closing**
Thank you very much for your guidance throughout the project. I will apply your remarks before the defense.
