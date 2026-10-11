# AirWindow — demo script (target 2:50, hard limit 3:00)

**Flow:** campus registration → upcoming activity → forecast warning → alternative time → coordinator action →
notification → stored action history → impact.

## Before recording

- **Data:** use the labelled SYNTHETIC scenario for a reproducible "warning + alternative" story:
  `.\.venv\Scripts\python.exe backend\scripts\serve.py --demo synthetic` (or deploy with `-DataMode replay -Replay synthetic`).
  The header reads **REPLAY · captured 2026-10-11 11:00:00 UTC · SYNTHETIC**. Say so on camera.
- For the genuine-data moment, keep a second tab on the live app (`serve.py` with no `--demo`). In live data on 11 Oct, Delhi
  tomorrow 07:30 showed **US AQI 158 with no permitted time under 150**, which is the "no eligible alternative" case.
- **If deployed:** subscribe your own email in Setup and **click the AWS confirmation link before recording**. Open the
  CloudWatch log group `/aws/lambda/airwindow-assess` and the DynamoDB table in the console.
- **If AWS is still blocked:** do **not** imply deployment. Use the AWS segment's fallback below.

---

**0:00–0:20 · Problem**
> "I coordinate outdoor PE at a Delhi school. In October the air is bad most days, but not equally bad at every hour.
> I need to know *which* sessions are at risk tomorrow, what lower-pollution time I'm allowed to use, and a record of what we did."

**0:20–0:45 · Campus registration + timetable** (My campus tab)
- Sign in. Locally the panel says *"Local development sign-in — not Cognito"*; on AWS it is Cognito.
- Register "Demo Public School" at Connaught Place. The timezone is detected as **Asia/Kolkata** and the threshold is **≤ 150**.
  Point out that it's flagged as a **demo record** automatically because the data is synthetic.
- Setup: Morning PE, daily 07:30, 60 min, **~40 participants (estimate only, no names)**, alternative window 13:30–16:00.

**0:45–1:20 · Forecast warning**
- Click **Check upcoming activities now**: *"Same path as the scheduled job: 3 assessed · 2 new warnings"*.
- Click it again: **0 new warnings**. "Repeated runs don't spam people."
- Open Monday's action card: **US AQI 178 (Unhealthy) exceeds 150**, index 96.0 µg·h/m³, alternative **13:30–14:30, AQI 128,
  −54.2% PM2.5 index**. Point at the named standard, the evidence (source, valid and retrieved times, ~45 km, SYNTHETIC), the AirNow
  **US-AQI** guidance ("not an Indian directive"), and *"Indoor air quality is unverified."*

**1:20–1:50 · Coordinator action + bulletin**
- Click **Accept time** for 13:30–14:30. The card records the decision with **−54.2% (same location, duration, source and forecast
  retrieval)** and *"a recorded decision is not proof the change happened."*
- Click **हिन्दी**. The deterministic Hindi bulletin appears first, then the separately labelled *AI-worded version (NVIDIA API fallback)*.
  "If the model changes any number or time, we throw it away. That happened in testing: it appended a word count."
- For today's session, which has already started, click **Held as planned**. Outcome is recorded separately from acceptance.

**1:50–2:25 · Notification + AWS evidence**
- *If deployed:* in Setup, the subscription shows **Confirmed**. Click **Send test notification**: *"Publish accepted
  (MessageId …)"*. Show the email arriving. Say: "publish accepted is not proof anyone read it, so the warning has an Acknowledge
  button." Then show `.\scripts\verify-aws.ps1`: two Lambda invocations (**second: alerts_created 0**), DynamoDB counts by type,
  the Scheduler schedule, and CloudWatch log lines.
- *If AWS is still blocked (current state):* say plainly *"This build is not deployed. The AWS account isn't activated."* Show the
  warning's status chip **"Prepared, not sent (local mode)"**, then `infra/template.yaml` (Cognito authorizer, DynamoDB, Scheduler,
  SNS), `sam build` succeeding, and the moto test run (`pytest tests/test_aws_adapters.py`). Call it **emulated**, not AWS.

**2:25–2:45 · History + community + impact**
- **History** tab: registration → activity → assessment → alert → decision → outcome, each with actor and time.
- **Reports**: one submitted "open burning at the east gate" report moving through Reviewed → Assigned → Action recorded →
  Resolution reviewed, still marked *"not independent verification … does not show emissions were reduced."*
- **Impact** tab: *Genuine usage* shows 0. Switch to *Demo records* to see the counts. "Participant-sessions are estimates, not
  unique people. The index change is modelled, not a health outcome."

**2:45–2:55 · Close**
> "AirWindow turns a forecast into a decision, a warning and an accountable record, and it's honest about what the data can't tell you."
