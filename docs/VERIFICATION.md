# Verification log

What was actually run and observed on 2026-10-11. "Emulated" means moto (a local AWS API emulator), not AWS.

## 1. Automated tests

| Suite | Result |
|---|---|
| Backend pytest (`cd backend; ..\.venv\Scripts\python.exe -m pytest -q`) | **118 passed** |
| Frontend vitest (`npm test`) | **27 passed** |
| Frontend type-check + production build (`npm run build`) | passes |
| `sam validate --lint` (SAM CLI 1.168.0) | valid |
| `sam build` (no Docker) | succeeds; both functions contain `_pydantic_core.cpython-313-x86_64-linux-gnu.so`; **no `.env` or local data in the artifacts** |
| PowerShell scripts (`deploy.ps1`, `verify-aws.ps1`, `teardown.ps1`) | parse without errors |

Behaviours covered by tests (see `backend/tests/`):
- **AQI and planner:** boundaries, half-up rounding, Beyond AQI, invalid → Unavailable; partial overlaps, missing-data exclusion,
  ranking ties, no eligible window (never "safe"), baseline comparison, +05:30 and DST, multiple permitted ranges.
- **Campus workflow (`test_campus.py`):**
  - creating an organisation and activity;
  - campus-timezone occurrences (07:30 IST → 02:00Z);
  - threshold breach with an alternative; breach with **no eligible alternative**;
  - missing forecast hour → unavailable (not green);
  - accept → separate completion (rejected before the time starts) → audit history;
  - keep-original requires a reason; indoor review stays "unverified"; shorten notes time + concentration;
  - **ownership isolation** (another coordinator gets 404 on 9 org routes and cannot list the org);
  - **duplicate scheduler invocations** (0 new alerts) and a **simulated crash between writes** (blocked by the conditional write);
  - a changed condition creates exactly one new alert per occurrence;
  - **provider failure** (no alerts, error recorded) and **stale data labelled**;
  - acknowledgement separate from publish; local-mode subscription/test notification never claimed as sent;
  - **reports**: submit → review → assign → action → resolution with role checks; photo type/size/magic-byte validation and signed URLs;
  - demo vs genuine separation;
  - bulletin validation (numbers, times, concentration units, word-count stripping, index values never sent to a model).
- **AWS adapters (`test_aws_adapters.py`, emulated):**
  - DynamoDB conditional writes, optimistic versions and both GSIs;
  - SNS subscribe with per-org filter policy and publish; *pending* confirmation via a stub, because moto auto-confirms;
  - S3 presigned POST policy (type + 1 B–5 MB) and the post-upload content check that deletes non-images;
  - Cognito claims parsing (ID tokens only);
  - **the full workflow through the real Lambda handler with API Gateway v2 events carrying JWT claims, on emulated DynamoDB + SNS**:
    401 without claims, 404 across organisations, alerts published once, 0 duplicates on a scheduled re-run.

## 2. Browser verification (local, built-in browser)

**Synthetic scenario** (`serve.py --demo synthetic`, LOCAL MODE; header shows *REPLAY · SYNTHETIC*):
- The local sign-in is labelled "not Cognito".
- Campus registered from the map location: timezone **auto-detected Asia/Kolkata**, threshold ≤ 150, automatically **DEMO RECORD**.
- Activity "Morning PE" daily 07:30, 60 min, ~40 participants, alternative window 13:30–16:00.
- *Check upcoming activities now*: **3 assessed · 2 new warnings · "Prepared, not sent (local mode)"**. Second click: **0 new warnings**.
- Monday card: **US AQI 178 (Unhealthy) > 150**, index 96.0, alternative **13:30–14:30 AQI 128, −54.2%**. AirNow US-AQI guidance
  labelled as not an Indian directive; indoor-unverified note; evidence panel.
- Accept time → decision recorded with comparison and the "not proof" note. Hindi bulletin: deterministic text plus a
  **separately labelled AI version from the NVIDIA API (accepted after validation)**. Acknowledge → "Acknowledged by Coordinator A".
  Today's past session → "held as planned".
- The scheduled-job handler run from the CLI (`python -m app.jobs`) on the same records: 3 assessed, **0 alerts created**, one CloudWatch EMF metric line emitted.

**Genuine live data** (`serve.py`, LOCAL MODE; a test organisation flagged as a test record):
- Real Open-Meteo retrieval at **2026-10-11T11:55:07Z**; timezone auto-detected server-side.
- Mon 12 Oct 07:30 IST: **US AQI 158 > 150, no permitted window under 150**; least-polluted 15:30–16:30 (−29.0%) labelled not safe.
  Tue 13 Oct: AQI 168, least-polluted 13:30–14:30 (−56.8%). Re-assessment: 0 new alerts.
- Report workflow completed in the UI (unverified → reviewed → assigned → action recorded → resolution reviewed, with caveats).
- Impact: *Genuine usage* all 0; *Demo/test* shows the 1 org, 3 assessed, 2 warnings, **0 publish accepted, 2 prepared-not-sent (local)**.

## 3. NVIDIA API (non-AWS fallback for bulletin wording)

- The key is stored only in git-ignored `backend/.env`. Model `nvidia/nemotron-3-super-120b-a12b` with thinking disabled answers in ~0.5 s.
- The first live run was **rejected by validation**: the model appended "(Word count: 118)". A separate output mislabelled the PM2.5 index
  as a concentration (µg/m³). Fixes: trailing word-count notes are stripped, index values are no longer sent, concentration units are rejected,
  and the prompt forbids meta commentary. After the fix, **4/4 live attempts (2 Hindi, 2 English) were accepted**.

## 4. AWS

| Check | Result |
|---|---|
| Default profile | no credentials |
| `burnwatch` profile (authorised by the user) | STS OK: `arn:aws:iam::448871778846:root` (root keys; an IAM user is recommended) |
| S3 / DynamoDB / Lambda / CloudFormation / CloudFront / EC2 | **blocked**: `NotSignedUp` / `SubscriptionRequiredException` / `OptInRequired` |
| `scripts/deploy.ps1` (guarded run) | stopped at the DynamoDB pre-check before creating anything |

**Not deployed. Not verified on AWS:**
- a real Cognito sign-up/sign-in;
- the JWT authorizer, and CloudFront forwarding `Authorization` (the AWS docs state AllViewerExceptHostHeader forwards all headers except Host);
- EventBridge Scheduler invocations;
- DynamoDB/SNS in AWS, a **confirmed SNS subscription and a test email to your own address**;
- Bedrock.

After the account is activated: `.\scripts\deploy.ps1`, confirm the subscription email, *Send test notification*, then `.\scripts\verify-aws.ps1`.

## 5. Round 1 (map and planner), still valid

- Live provider probes established the 0.4° cell behaviour, the GMT + unixtime requirement for +05:30, Beyond AQI values, and OpenAQ needing a key.
- Browser: map/legend/slider/chart/planner on live data; replay single-origin build; mobile 375 px layout.
