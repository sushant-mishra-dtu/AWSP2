# AirWindow

**AirWindow helps schools and colleges turn pollution forecasts into timely activity changes and accountable community action.**

Built for *WeMakeDevs × AWS Environmental Hacks* (Air track), 8–11 October 2026.
Primary user: a **school or college activity coordinator**. Primary demo location: **Delhi**. The map works worldwide.

> **Deployment status (11 Oct 2026): not deployed.** The infrastructure is written, linted and built
> (`sam validate --lint`, `sam build`). The AWS account available to us (`burnwatch` profile) is not
> activated for S3, DynamoDB, Lambda, CloudFormation or CloudFront (`NotSignedUp` /
> `SubscriptionRequiredException` / `OptInRequired`). The app runs locally in a clearly labelled
> **LOCAL MODE**. See [§4](#4-aws-usage-implemented-vs-tested-vs-deployed) and
> [docs/VERIFICATION.md](docs/VERIFICATION.md).

---

## 1. The problem

In Delhi NCR, October–November brings some of the year's worst air. Coordinators still have to run assemblies,
PE, sports practice and events. Pollution changes through the day, but a single "AQI now" number doesn't tell
a coordinator *which* of tomorrow's outdoor sessions are at risk, what a lower-pollution alternative within
school hours would be, who was warned, or what was actually done.

## 2. What AirWindow does

**Explore (public, no sign-in).** A world map of CAMS Global model cells (~45 km) coloured by provider-calculated
US AQI. It has a 48-hour time slider, a selected-location panel and chart, and the original activity planner.

**My campus (coordinator, signed in).** The journey is: campus registration → upcoming activity → forecast warning →
alternative time → coordinator action → notification → stored action history.

1. **Register a campus:** name, location (search or map click), IANA timezone (auto-detected and editable),
   and a planning threshold (peak US AQI). Records created from replay/synthetic data are always flagged as **demo records**.
2. **Activity timetable:** name, kind, weekdays, planned start, duration, an **aggregate participant estimate**
   (no names, no medical data), and permitted alternative windows.
3. **Action cards** for each occurrence in the next 48 h (in the campus timezone):
   - the planned time and campus location;
   - the forecast AQI category, with the standard named: *US AQI calculated by Open-Meteo from CAMS Global modelled concentrations*;
   - the PM2.5 pollution-time index (µg·h/m³);
   - whether the threshold is exceeded;
   - the lower-pollution alternative, or, if none qualifies, the least-polluted time labelled **"not a safe window"**;
   - provenance: source, valid time, retrieval time, resolution, data mode and stale flag;
   - a concise deterministic explanation;
   - AirNow **US-AQI** school guidance, explicitly *not* an Indian directive (local restrictions take precedence);
   - the line *"Indoor air quality is unverified"*.
4. **Coordinator actions:** accept an alternative, shorten, postpone, cancel, flag an indoor option for review, or
   keep the original plan with a required reason. **Outcome** (held as planned / held as changed / not held) is a
   separate record, allowed only once the time has started, because acceptance is not proof that anything happened.
5. **Advance warnings:** the **EventBridge Scheduler → Lambda** job and the **"Check upcoming activities now"** button
   call the same `assess_org` code. That code:
   - de-duplicates by condition fingerprint, using conditional writes;
   - applies a per-occurrence cooldown;
   - retries failed publishes;
   - sends **opt-in SNS email** (per-organisation filter policy, pending vs confirmed shown separately).

   Statuses are *prepared / publish accepted / failed / no confirmed subscriber / cooldown / not sent (local)*.
   **Acknowledgement** is recorded only in the app.
6. **Audit history:** an append-only log of every registration, change, decision, alert, notification and report step.
7. **Coordinator bulletin (English / हिन्दी):** a deterministic bulletin is always produced. Optional AI wording comes
   from Amazon Bedrock, with the **NVIDIA API as fallback**. It is shown separately and rejected if it adds any
   number, time or concentration unit not present in the facts.

**Community action tracker.** Signed-in staff can report:
- open waste burning;
- construction dust;
- vehicle idling at the gate;
- other visible pollution concerns.

Each report records the location, time, a short description and an optional private photo (JPEG/PNG/WebP, ≤ 5 MB, type checked by magic bytes).
Reports move through **Submitted → Reviewed → Assigned → Action recorded → Resolution reviewed**, with campus
tasks such as investigating burning or placing a no-idling reminder. Reports stay **unverified** and are never published or sent to authorities.
They are never linked to the AQI, and a resolution is never presented as an emissions reduction.

**Impact (public, aggregate).** The panel shows:
- organisations registered;
- occurrences assessed;
- recommendations proposed, accepted, declined and completed;
- **participant-sessions** (coordinator estimates, not unique people);
- warnings, publish-accepted, failed and acknowledged counts;
- reports reviewed and follow-ups.

It also lists modelled PM2.5-index comparisons for accepted changes, all from the same location, duration, source and forecast retrieval.
**Genuine usage and demo records are separated.** Nothing is labelled as a health improvement or an ambient-pollution reduction.

## 3. Architecture

```
Browser ─HTTPS─► CloudFront ─(default)──► S3 site bucket (private, OAC)
                    └─(/api/*, no cache)─► API Gateway HTTP API ─► Lambda "api" (FastAPI + Mangum)
                                            │  Cognito JWT authorizer on /api/orgs*, /api/me
EventBridge Scheduler (rate 30 min) ───────► Lambda "assess" (same assess_org path)
Lambda ──► DynamoDB single table (orgs, activities, occurrences, actions/history, alerts, subscriptions, reports, forecast cache)
       ──► SNS topic (email, per-org filter policy)      ──► S3 evidence bucket (private, presigned POST/GET)
       ──► Open-Meteo / OpenAQ / NVIDIA API (HTTPS)      ──► Bedrock (optional)
CloudWatch: structured logs (14-day retention), EMF metrics (AlertsCreated, DuplicateAlertsSkipped, PublishAccepted…), error alarm
AWS Budgets: optional monthly cost alert
```

## 4. AWS usage: implemented vs tested vs deployed

| Service | Product function | Implemented | Tested (how) | Deployed |
|---|---|---|---|---|
| S3 (site) | Frontend assets, private with OAC | ✅ | `sam validate --lint` | ❌ |
| S3 (evidence) | Private report photos, presigned POST/GET, 180-day lifecycle | ✅ | **moto**: POST policy (type + size), magic-byte check, deletion | ❌ |
| CloudFront | HTTPS delivery; `/api/*` to API, Authorization forwarded | ✅ | lint | ❌ |
| API Gateway HTTP API | Public read routes; Cognito JWT on coordinator routes; throttling | ✅ | lint; Lambda handler driven with API GW v2 events incl. JWT-claims context | ❌ |
| Lambda | API + scheduled assessment | ✅ | `sam build` (Linux wheels); handlers invoked locally | ❌ |
| DynamoDB | All campus records, alert de-duplication, forecast cache | ✅ | **moto**: conditional puts, optimistic versions, both GSIs, full workflow | ❌ |
| EventBridge Scheduler | Periodic assessment (`ScheduleV2`, retry policy) | ✅ | handler run locally; duplicate-invocation tests | ❌ |
| SNS | Opt-in email warnings, per-org filter policy | ✅ | **moto** subscribe/publish; stub for *pending* (moto auto-confirms) | ❌ |
| Cognito | Coordinator sign-up/in, ID token → JWT authorizer | ✅ | claims parsing + ownership tests; frontend flow **not** exercised against a real pool | ❌ |
| CloudWatch | Log retention, EMF metrics, error alarm | ✅ | EMF line emitted locally | ❌ |
| AWS Budgets | Monthly cost alert (optional parameter) | ✅ | lint | ❌ |
| Bedrock | Bulletin wording (Converse API) | ✅ code + validation | stubbed; no model access | ❌ |
| *(non-AWS)* NVIDIA API | Fallback bulletin wording | ✅ | **live calls** (EN/HI) through validation | — |

**moto** is a local AWS API emulator. It proves our boto3 calls and logic, not that anything runs in AWS.
**Planned after account activation:** deploy, confirm a real SNS email subscription, send a test notification,
create a real Cognito user and run `scripts/verify-aws.ps1` for Lambda/DynamoDB/SNS/Scheduler evidence.

**LOCAL MODE** (what runs today) uses a SQLite file instead of DynamoDB, a password-less development sign-in instead of Cognito,
a notifier that **prepares but never sends**, and a local folder instead of S3. All of this is stated in the UI and at `/api/runtime`.
Nothing in local mode is presented as AWS.

**Least privilege:**
- the API function: DynamoDB CRUD on the one table; `sns:Publish/Subscribe` on the topic and `Unsubscribe/GetSubscriptionAttributes` on its subscriptions;
  `s3:Put/Get/DeleteObject` on `evidence/reports/*`; `bedrock:InvokeModel` only if a model id is configured;
- the assessment function: DynamoDB CRUD, `sns:Publish` and `GetSubscriptionAttributes`.

There is no VPC, NAT or public bucket.

**Cost controls:**
- on-demand DynamoDB;
- API throttling (20 rps / burst 40);
- schedule every 30 min, configurable, with `ScheduleState=DISABLED` available;
- at most 10 organisations per run;
- 100 map cells per request;
- 30-min forecast cache shared through DynamoDB;
- 14-day log retention;
- 180-day evidence lifecycle;
- SNS email (free tier);
- an optional `BudgetEmail` monthly budget.

## 5. Data integrity and limitations

- **Sources:** Open-Meteo Air Quality API (`domains=cams_global`, CAMS Global model, ~45 km, 3-hourly native step) for
  pollutants and provider-calculated US AQI. Open-Meteo Forecast for weather, as **context only**. OpenAQ v3 (optional key) for
  **observations**, shown as raw values and never AQI-coloured. Measured, modelled, stale-cached, replay and synthetic data are labelled distinctly.
- **One standard:** US AQI only; Indian NAQI thresholds are never mixed in. AirNow guidance is labelled US-AQI guidance
  (EPA-456/F-14-003, Aug 2014) and is not an Indian directive. Local official restrictions take precedence.
- **Resolution:** ~45 km. There are no street-, school- or neighbourhood-level differences and no clean-air routes. The UI repeats this at street zoom.
- **Missing or invalid data stays unavailable** (grey) and is never green. A window touching a missing hour is never ranked.
- **Timezones:** the provider is always queried in GMT + unix time and converted with IANA `zoneinfo`/`Intl`, including the +05:30 offset and DST.
- **Planner:** PM2.5 × overlap-hours index, with partial hours weighted. It is a comparative planning number, **not dose or health risk**, and
  rescheduling does not reduce ambient pollution. A shortened activity's comparison reflects both time and concentration. No indoor
  improvement is ever estimated.
- **US AQI above 500** is shown as **"Beyond AQI"**, not capped. Open-Meteo's PM sub-indices use 24-h rolling averages.
- **Caches:** an in-memory TTL cache plus a DynamoDB forecast cache with explicit `expires_at` checks (TTL deletion is only housekeeping and may lag).
  Stale data is served only when a refresh fails, and is labelled.

## 6. Run locally (Windows PowerShell)

Prerequisites: Python 3.13 (`py -3.13`), Node.js ≥ 22.12, Git.

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements-dev.txt
Copy-Item .env.example backend\.env          # optional: NVIDIA_API_KEY, OPENAQ_API_KEY
cd frontend; npm ci; cd ..
```

Run the API (choose one), then the frontend in a second terminal:

```powershell
.\.venv\Scripts\python.exe backend\scripts\serve.py                     # live data, LOCAL MODE
.\.venv\Scripts\python.exe backend\scripts\serve.py --demo synthetic    # SYNTHETIC adverse-air scenario (demo)
.\.venv\Scripts\python.exe backend\scripts\serve.py --demo real         # REAL captured Delhi replay
```

```powershell
cd frontend; npm run dev        # http://127.0.0.1:5173
```

Run the scheduled job's handler locally (same code EventBridge Scheduler invokes):
`cd backend; ..\.venv\Scripts\python.exe -m app.jobs`

Tests:

```powershell
cd backend; ..\.venv\Scripts\python.exe -m pytest -q; cd ..     # 118 tests (incl. moto-emulated AWS)
cd frontend; npm test; npm run build; cd ..                      # 27 tests + type-check + build
```

Fixtures: `backend\scripts\capture_replay.py` re-captures real Delhi responses, and `backend\scripts\make_synthetic_scenario.py`
regenerates the SYNTHETIC scenario.

## 7. Deploy to AWS, verify, tear down

Requirements: an **activated** AWS account, AWS CLI v2 credentials (preferably an IAM user/role, not root keys), and SAM CLI
(`py -3.13 -m venv .tools-venv; .\.tools-venv\Scripts\pip install aws-sam-cli`). Docker is not needed.

```powershell
$env:AWS_PROFILE = "<profile>"
.\scripts\deploy.ps1 -BudgetEmail you@example.org          # live data, stack "airwindow", ap-south-1
.\scripts\deploy.ps1 -DataMode replay -Replay synthetic    # labelled demo deployment
.\scripts\verify-aws.ps1                                   # Lambda invokes, DynamoDB counts, SNS states, logs
.\scripts\teardown.ps1                                     # empties buckets, deletes the stack (data is lost)
```

`deploy.ps1`:
1. checks the account can use DynamoDB;
2. stages a clean Lambda source (never `backend/.env` or local data);
3. runs `sam build` and `sam deploy` (secrets passed as `NoEcho` parameters), then sets `AppUrl`;
4. builds and uploads the frontend and invalidates CloudFront;
5. smoke-tests `/api/runtime` and checks that unauthenticated `/api/orgs` returns **401** from the JWT authorizer.

## 8. Original contributions

All application code was written for this hackathon. This covers:
- the planner and US AQI classifier;
- the campus domain (cards, decisions, outcomes, audit history);
- the assessment / de-duplication / notification engine;
- the reports workflow and evidence handling;
- impact accounting;
- the bulletin validator;
- the DynamoDB and SQLite stores;
- the React UI;
- the SAM template;
- the PowerShell scripts;
- the tests: **118 pytest + 27 vitest**.

No code was copied from other AQI applications. Libraries and services are listed in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## 9. AI-tool disclosure

- **Development:** built with an AI coding assistant (Claude Code, Claude Opus 5.5) working under the team's direction. It wrote code,
  tests, infrastructure and docs and ran the verification. Commits carry `Co-Authored-By` trailers. The Hindi bulletin templates
  were translated with AI assistance and should be checked by a fluent reviewer.
- **In the product:** classification, thresholds, ranking, alerts and explanations are deterministic code. AI is used only to re-word
  or translate the bulletin (Bedrock if configured, else the NVIDIA API, model `nvidia/nemotron-3-super-120b-a12b`). Only the
  activity and forecast summary is sent (no emails or personal data). Any output that adds a number, time or concentration unit is
  rejected, the AI text is shown separately from the evidence, and the deterministic bulletin stays authoritative.

## 10. Repository layout

```
backend/app/        FastAPI app: planner, aqi, campus, alerts, reports, impact, bulletin, store, auth, notify, evidence, jobs
backend/tests/      pytest (planner, AQI, providers, API, campus workflow, moto-emulated AWS adapters)
backend/fixtures/   replay_delhi.json (REAL capture) · scenario_delhi_synthetic.json (SYNTHETIC)
backend/scripts/    serve.py · capture_replay.py · make_synthetic_scenario.py
frontend/src/       React UI (map, planner, campus workspace, impact)
infra/template.yaml AWS SAM
scripts/            deploy.ps1 · verify-aws.ps1 · teardown.ps1
docs/               DEMO_SCRIPT.md · VERIFICATION.md
```
