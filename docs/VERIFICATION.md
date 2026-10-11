# Verification log (2026-10-11)

What was actually run and observed. Nothing here is aspirational.

## Automated tests

| Suite | Command | Result |
|---|---|---|
| Backend (pytest) | `cd backend; ..\.venv\Scripts\python.exe -m pytest -q` | **93 passed** |
| Frontend unit (vitest) | `cd frontend; npm test` | **27 passed** |
| Frontend type-check + build | `npm run build` (tsc 7.0.2 + Vite 8.3.4) | **passes** |

Backend coverage by behaviour:
- AQI: every band boundary, half-up rounding (50.5 → 51, 500.5 → Beyond AQI), invalid/negative/NaN/∞/bool/string → Unavailable, legend order.
- Planner: full and partial hourly overlaps (30, 60, 120 min; 15-min offsets), window ending on an interval boundary,
  missing PM2.5/AQI exclusion (incl. NaN and absent intervals), ranking ties (index → peak AQI → earliest),
  no eligible window (never "safe"), threshold met but category still unhealthy, baseline % change,
  same-window, incomplete baseline, zero-index baseline, baseline outside permitted hours (worse alternative reported honestly),
  Asia/Kolkata +05:30 partial-hour alignment, New York DST (summer/winter offsets, fall-back day durations),
  past windows excluded, all-past day, invalid inputs.
- Providers/cache: 429 not retried, 5xx retried once then error, timeout, invalid JSON, 400 reason surfaced, empty hourly rejected,
  null/∞/bool cleaning, 0.4° lattice snapping, bounded LRU, fresh → stale → expired, stale value carries original retrieval time.
- API: provider failure returns an error body with no data fields; rate limit → 503; success carries full provenance;
  **stale cache presentation** (served only after refresh failure, flagged `stale`, note with retrieval time);
  weather failure doesn't block pollution; grid zoom gate makes no provider calls; grid batching + dedup + cache;
  grid failure → cells "unavailable" with all-null values; stations without key → explained "unavailable";
  stations with key → raw observations, inactive stations omitted, key sent only as header and never echoed;
  plan validation 400; synthetic end-to-end plan; replay labelling (`mode`, `synthetic`, capture time as "now"; uncaptured → 404).
- Lambda adapter: API Gateway HTTP API v2 events through the real `app.main.handler` (Mangum).

## Live provider probes

- Open-Meteo Air Quality (`cams_global`): Delhi, multi-location batching, transects (Delhi/London/Sydney) establishing
  the ~0.4° piecewise-constant cells and that returned coordinates are 0.1°-rounded, `past_hours`/`forecast_hours`,
  and the `timezone=auto` +05:30 half-hour label shift (hence GMT + unixtime everywhere).
- Open-Meteo Forecast (weather + timezone) and Geocoding: OK.
- OpenAQ v3 without key: HTTP 401 (key required). No key was available, so live station observations were **not** verified;
  the adapter was built from the official OpenAPI schema (`/v3/locations`, `/v3/locations/{id}/latest`) and tested with mocked payloads.

## Browser verification (local, live data)

Vite dev server + uvicorn, built-in browser:
- Map loads at Delhi with 28–42 labelled 0.4° cells; values above 500 render "Beyond AQI · N"; legend persistent.
- Location selection by demo chip, map click, and search ("Mumbai" → flies there; 8 cells load on demand; panel 219 Very unhealthy, O₃ dominant).
- Slider moves map cells and location panel together (Mumbai cell/panel 219 → 230 for +1 h).
- Chart: hourly PM2.5 step area + US AQI line, now marker, selected hour, permitted hours, baseline and best windows.
- Planner (tomorrow, 07:00–17:00, 60 min, planned 07:30): threshold ≤ 100 → "No window meets your threshold … not a safe window";
  threshold ≤ 200 → lowest-index eligible 15:30–16:30, **−29.0%** PM2.5 pollution-time index (53.9 vs 75.9 µg·h/m³).
- Street-level zoom shows the "~45 km model cell" notice; mobile 375 px layout usable (compact persistent legend, slider above attribution).

Production-like single origin (`STATIC_DIR=frontend/dist`, `DATA_MODE=replay`, one uvicorn process — same topology as CloudFront `/api/*` routing):
- Header shows "REPLAY · captured 2026-10-11 10:51:31 UTC"; uncaptured cells grey and counted as unavailable;
  clicking an uncaptured location shows "Pollution data is unavailable … No simulated or placeholder values are shown."

## AWS

| Step | Result |
|---|---|
| `sam validate --lint` (SAM CLI 1.168.0) | **valid** |
| `sam build` (no Docker) | **succeeded**; bundle contains `_pydantic_core.cpython-313-x86_64-linux-gnu.so` (Lambda-compatible) |
| Default AWS profile | no credentials (`NoCredentials`) |
| `burnwatch` profile (authorised by the user) | STS OK: `arn:aws:iam::448871778846:root`, region ap-south-1 |
| CloudFormation / Lambda / S3 / API Gateway / CloudFront / EC2 on that account | **blocked**: `OptInRequired` / `SubscriptionRequiredException` / `NotSignedUp` ("Your account is not signed up for the S3 service") |

**Deployment status: NOT deployed.** The account must finish AWS registration/activation before any stack can be created.
After activation (and preferably with an IAM user/role instead of root keys):

```powershell
$env:AWS_PROFILE = "burnwatch"     # or your IAM profile
.\scripts\deploy.ps1               # prints the CloudFront URL and smoke-tests /api/health
.\scripts\teardown.ps1             # removes everything
```
