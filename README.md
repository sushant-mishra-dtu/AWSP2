# AirWindow

**Find a lower-pollution time for outdoor school activities.**
Built for *WeMakeDevs × AWS Environmental Hacks* (Air track), 8–11 October 2026.

AirWindow is a map-first planner for school and college activity coordinators. You pick a place, see
the modelled air-quality forecast for the next 48 hours, enter how long the activity lasts and which
hours are allowed, and AirWindow compares your planned slot with the lowest-pollution window,
showing the evidence and limits of the forecast.

> Delhi is the polished demo location. Any place in the world works on demand.

---

## 1. The problem

In Delhi NCR, October and November bring some of the worst air of the year. Coordinators still have
to schedule assemblies, PE periods, sports practice and outdoor events. Pollution changes through
the day, but most tools show a single "current AQI" number, which doesn't answer the actual question:

*"If we must be outside for 60 minutes between 07:00 and 17:00 tomorrow, when is the least-bad
time, how much better is it than what we planned, and how much can we trust that?"*

## 2. What it does (core journey)

1. **Open the map.** A world base map with a labelled sample grid of modelled US AQI cells around Delhi.
2. **Search or click a location.** City search (Open-Meteo geocoding), a "use my location" button, or any map click.
3. **Inspect conditions.** Provider-calculated US AQI with its category, the highest sub-index
   (e.g. "PM10, 24-h rolling avg"), PM2.5/PM10/NO₂/O₃/SO₂/CO with units, and weather as context only.
4. **View 24–48 hours.** A step chart of hourly PM2.5 and US AQI. One time slider moves the map
   cells, the location panel and the chart together.
5. **Plan the activity.** Choose the day (today/tomorrow in the location's timezone), duration
   (30/60/120 min), permitted hours, your planned start and a planning threshold (peak AQI).
6. **Compare.** Your planned slot vs the lowest-index eligible window, with the % change in
   PM2.5 pollution-time index, the next options, and a deterministic explanation.
7. **Understand the evidence.** Source, model, resolution, time step, retrieval time, cache/stale
   status, model grid point and distance, plus explicit limitations.

If no window meets the threshold, the app says so plainly and labels the least-polluted
option **"not a safe window"**.

## 3. Architecture and AWS usage

```
Browser ──HTTPS──► CloudFront ──(default)──► S3 bucket (private, OAC-signed reads only)
                     │
                     └──(/api/*)──► API Gateway HTTP API (throttled) ──► Lambda (Python 3.13)
                                                                          FastAPI + Mangum
                                                                          │ bounded TTL cache
                                                                          ├─► Open-Meteo Air Quality (CAMS Global)
                                                                          ├─► Open-Meteo Forecast + Geocoding
                                                                          └─► OpenAQ v3 (optional, key server-side)
```

| AWS service | Why it is used |
|---|---|
| **AWS Lambda** (python3.13, 512 MB, x86_64) | Runs the FastAPI API via Mangum: provider calls, caching, AQI classification, the planner algorithm. |
| **Amazon API Gateway HTTP API** | Public API front door; default route throttling (20 rps, burst 40) protects the free upstream APIs. |
| **Amazon S3** (private) | Holds the built React site. Block Public Access is on, encryption is SSE-S3, and the bucket policy only allows CloudFront (OAC) and denies non-TLS access. |
| **Amazon CloudFront** + Origin Access Control | Serves the site over HTTPS. `/api/*` is routed to the HTTP API with caching disabled, so the app is single-origin (no CORS needed). |
| **CloudWatch Logs** | Lambda logs with 14-day retention. |
| **AWS SAM / CloudFormation** | `infra/template.yaml` defines everything; `sam build` packages Linux wheels without Docker. |

**Least privilege:** the function role is SAM's default `AWSLambdaBasicExecutionRole` (logs only);
the function reads no other AWS resources. There is no VPC or NAT gateway (the function only needs
outbound HTTPS to public APIs), no database and no authentication. Personal activity preferences
live in the browser's `localStorage`.

**Cost:** within free tiers for a hackathon demo (Lambda and API Gateway per-request, CloudFront and S3 minimal).

## 4. Data provenance

| Data | Source | Type | Shown as |
|---|---|---|---|
| PM2.5, PM10, NO₂, O₃, SO₂, CO (µg/m³) | Open-Meteo Air Quality API, `domains=cams_global` (Copernicus CAMS Global forecast) | **Modelled forecast** | Values with units, chart, map cells |
| US AQI and sub-indices | Calculated **by Open-Meteo** from the modelled concentrations | Provider-calculated index | "Modelled US AQI (provider-calculated)" |
| Temperature, humidity, wind, precipitation | Open-Meteo Forecast API | Modelled weather | "Weather context", never used in AQI or ranking |
| Station observations | OpenAQ API v3 (optional, needs a server-side key) | **Observation** | Separate neutral markers with raw value, units, age, distance, provider/owner/licence. Never AQI-coloured. |
| Place search | Open-Meteo Geocoding (GeoNames) | Gazetteer | Search results with timezone |

Every reading keeps its coordinates (the model grid point the provider resolved), value, units,
AQI standard where applicable, source, valid interval (UTC), retrieval time, data type and model
resolution. Observations, forecasts and cached results are labelled distinctly. Different AQI
standards are never averaged together; the only index used is US AQI.

### Things we verified against the real APIs (11 Oct 2026)

- **Grid:** CAMS Global values are piecewise-constant over ~0.4° cells (transects across Delhi and
  London show steps at ±0.2° around multiples of 0.4°). The coordinates Open-Meteo returns are
  rounded to 0.1° and are *not* cell centres. AirWindow therefore samples the map on a
  0.4°-spaced lattice (one sample per ~45 km cell, deduplicated by construction) and draws each
  sample as an approximate 0.4° footprint. A Sydney transect showed edges that don't align exactly,
  so footprints are labelled approximate.
- **Time:** CAMS Global's native step is 3-hourly (provider documentation); the API serves hourly values.
- **Timezones:** with `timezone=auto`, Asia/Kolkata (UTC+05:30) responses label each value 30 minutes
  away from the model's UTC step. AirWindow always requests `timezone=GMT&timeformat=unixtime` and
  converts with IANA `zoneinfo`/`Intl`, including DST.
- **AQI above 500:** Open-Meteo returns US AQI values above 500. In NW India in October the PM10
  24-h sub-index often dominates (e.g. 865 with PM10 hourly 410 µg/m³). These display as
  **"Beyond AQI"**, never capped.
- **OpenAQ:** v3 requires an API key (unauthenticated requests return 401). Without a key the
  station layer explains that it is off and everything else keeps working.

### CPCB (data.gov.in)

The optional Indian CPCB adapter was **not implemented** in this sprint. Its `pollutant_avg`
fields are not documented clearly enough to treat as raw concentrations or a station AQI, and
the core flow came first.

## 5. The calculation

### US AQI classification (`backend/app/aqi.py`, mirrored in `frontend/src/aqi.ts`)

| Rounded AQI | Category | Colour |
|---|---|---|
| 0–50 | Good | green `#00e400` |
| 51–100 | Moderate | yellow `#ffff00` |
| 101–150 | Unhealthy for sensitive groups | orange `#ff7e00` |
| 151–200 | Unhealthy | red `#ff0000` |
| 201–300 | Very unhealthy | purple `#8f3f97` |
| 301–500 | Hazardous | maroon `#7e0023` |
| > 500 | **Beyond AQI** (explicit label) | dark maroon `#3d0011` |
| missing / NaN / ±∞ / negative / non-numeric | **Unavailable** | grey `#9ca3af` |

**Rounding:** decimal inputs are rounded **half-up** to an integer *before* classification
(50.4 → 50 Good, 50.5 → 51 Moderate, 500.5 → 501 Beyond AQI). Negativity is checked before
rounding (−0.2 is Unavailable). Colour is always accompanied by the text label.

### Activity-window planner (`backend/app/planner.py`)

Inputs: location (→ IANA timezone), local date, permitted start/end, duration, planned (baseline)
start, planning threshold (peak AQI).

1. Candidate windows start every **15 minutes** within the permitted hours (wall-clock local time,
   converted to UTC with `zoneinfo`) and must end by the permitted end. Duration is elapsed time,
   so DST days are handled.
2. For each window, every hourly forecast interval `[t, t+1h)` it overlaps contributes
   **PM2.5 × overlap hours**. Partial overlaps are weighted (e.g. a 06:00–07:00 IST window covers half
   of the 00:00 UTC and half of the 01:00 UTC interval).
   **PM2.5 pollution-time index = Σ PM2.5ᵢ · Δtᵢ** in **µg·h/m³**.
3. **Peak AQI** = max provider US AQI over every touched interval.
4. A window touching any interval with missing PM2.5 or AQI is **incomplete and never ranked**.
5. Windows that have already started are not recommended.
6. **Eligible** = complete, future, within permitted hours, peak AQI ≤ threshold.
   Ranking: index ↑, then peak AQI ↑, then earliest start.
7. **Comparison** uses the *same* fetched series (same location, duration, source and forecast
   retrieval) for baseline and alternative. A % change is reported only if both are complete and
   the baseline index is > 0. A worse alternative is reported as worse.
8. **No eligible window:** the status says so, and the least-polluted complete window is
   labelled as exceeding the threshold and **not a safe window**.
9. Explanations are generated deterministically from the computed numbers. No LLM is used anywhere.

**Worked example (replay fixture, captured 2026-10-11 10:51 UTC):** Connaught Place, tomorrow,
07:00–17:00, 60 min, planned 07:30, threshold ≤ 200 → lowest-index eligible window
**15:30–16:30 IST**, index **53.9** vs **75.9 µg·h/m³** for 07:30–08:30, i.e. **−29.0%**. Both
are still "Unhealthy" (peak AQI 155 vs 158), and the app says so. With threshold ≤ 100, no window
qualifies and the 15:30 slot is shown as "least-polluted, exceeds threshold, not a safe window".

The index is a **comparative planning number**: not inhaled dose, exposure or medical risk.
Moving an activity changes *when* people are outside; it does not reduce ambient pollution.

## 6. Limitations

- ~45 km model resolution: no street-, school- or neighbourhood-level differences, and values jump at
  cell edges. The UI repeats this at street zoom.
- Provider US AQI uses 24-h rolling averages for PM2.5/PM10, so hourly AQI moves slowly; ranking uses hourly PM2.5.
- Forecasts can be wrong; the app is not an official CPCB/NAQI or EPA product and is not medical advice.
- Weather is context only; the app does not infer pollution causes from weather.
- The Lambda cache is in-memory per warm container. Stale data (served only when a refresh fails, up to
  6 h old) is always labelled with its original retrieval time.
- Open-Meteo's free API is for non-commercial use with rate limits; the map loads at most 100 cells per
  view (sparser sampling when zoomed out, nothing below that) and caches cells for 30 min.

## 7. Run locally (Windows PowerShell)

Prerequisites: Python 3.13 (`py -3.13`), Node.js ≥ 22.12, Git.

```powershell
# 1. Backend
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements-dev.txt
Copy-Item .env.example backend\.env      # optional: edit DATA_MODE / OPENAQ_API_KEY
.\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --port 8000

# 2. Frontend (new terminal)
cd frontend
npm ci
npm run dev          # http://127.0.0.1:5173 (proxies /api to :8000)
```

Replay mode (reproducible demo; no network needed for Delhi):

```powershell
$env:DATA_MODE = "replay"; .\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --port 8000
```

Re-capture the Delhi fixture from the real APIs: `.\.venv\Scripts\python.exe backend\scripts\capture_replay.py`.

Tests and checks:

```powershell
cd backend;  ..\.venv\Scripts\python.exe -m pytest -q;  cd ..
cd frontend; npm test; npm run build;                    cd ..
```

## 8. Deploy to AWS / tear down

Prerequisites: AWS CLI v2 with credentials (`aws configure` or `aws login`), and SAM CLI
(`py -3.13 -m venv .tools-venv; .\.tools-venv\Scripts\pip install aws-sam-cli`). Docker is not required.

```powershell
.\scripts\deploy.ps1                       # stack "airwindow" in ap-south-1 (Mumbai), live mode
.\scripts\deploy.ps1 -DataMode replay      # labelled replay mode
$env:OPENAQ_API_KEY = "<your key>"; .\scripts\deploy.ps1   # enable stations (NoEcho parameter)
```

The script runs `sam build` + `sam deploy`, builds the frontend, syncs it to the private bucket,
invalidates CloudFront, smoke-tests `/api/health` through CloudFront and prints the app URL.

Teardown (empties the site bucket, then deletes the stack):

```powershell
.\scripts\teardown.ps1
```

## 9. Original contributions

Written for this hackathon: the FastAPI service (provider adapters, bounded TTL cache with labelled
stale fallback, replay/fixture mode, 0.4° lattice sampling and dedup, grid batching and zoom gating),
the pure US AQI classifier, the activity-window planner and its deterministic explanations, the
React UI (map layers, synchronised slider/chart/panel, planner, evidence panel, responsive layout),
the SAM infrastructure, the PowerShell deploy/teardown scripts and the test suites
(93 pytest + 27 vitest). Libraries are listed in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## 10. AI-tool disclosure

This project was built with an AI coding assistant (Claude Code, model Claude Opus 5.5) working in
the repository under the team's direction: it probed the provider APIs, wrote the code, tests,
infrastructure and documentation, and ran the verification steps. The commit history is truthful
and carries `Co-Authored-By` trailers. **The running application uses no AI or LLM**: classification,
ranking and explanations are deterministic code.

## 11. Repository layout

```
backend/   FastAPI app (app/), tests/, fixtures/replay_delhi.json, scripts/capture_replay.py
frontend/  React + Vite + Tailwind + react-leaflet + Recharts
infra/     template.yaml (AWS SAM)
scripts/   deploy.ps1, teardown.ps1
docs/      DEMO_SCRIPT.md, VERIFICATION.md
```
