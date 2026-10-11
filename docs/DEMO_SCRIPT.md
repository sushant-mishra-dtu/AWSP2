# AirWindow — demo script (target 2:45, hard limit 3:00)

**Setup before recording**
- Open the deployed CloudFront URL (from `scripts/deploy.ps1` output) at desktop width (≥ 1280 px).
- In a second tab, open the AWS console on the `airwindow` CloudFormation stack (Resources tab), plus
  CloudWatch Logs for `/aws/lambda/airwindow-api`.
- Live numbers change hourly. For a reproducible recording, deploy with `-DataMode replay`. The header
  then shows **REPLAY · captured 2026-10-11 10:51 UTC**; say so on camera. The numbers below are from that capture.
- Clear the site's local storage, or set the planner to: Tomorrow · 60 min · 07:00–17:00 · planned 07:30 · threshold ≤ 100.

---

**0:00–0:20 · The problem**
> "I coordinate outdoor activities at a Delhi school. In October the air is bad almost all day, but not
> equally bad. A single 'AQI now' number doesn't tell me *when* tomorrow to hold a 60-minute PE period,
> or whether I should move it indoors. AirWindow answers that from forecast data, and shows how far to trust it."

**0:20–0:50 · Live map**
- Point at the header badge (LIVE DATA or REPLAY with its capture time).
- "Each square is a Copernicus CAMS Global model cell, about 45 km wide. The colours are US AQI as
  calculated by Open-Meteo, a modelled forecast rather than a local measurement." Point at the legend.
- Point at a dark cell: "Above 500 we say **Beyond AQI**, without capping it. The panel shows it's driven by the PM10 24-hour average."
- Zoom in to street level and show the notice: "The model can't tell one street or school from another, and the app says so at every zoom."

**0:50–1:20 · Selected location and forecast**
- Click **Connaught Place**: "Modelled US AQI 160, Unhealthy. The highest sub-index is PM2.5 on a
  24-hour rolling average. Pollutants are shown with units, and weather appears as context only."
- Point at **Data quality**: "0.4° resolution, 3-hourly native time step, the model grid point is 3.9 km
  from my point, and the retrieval time is shown."
- Drag the **time slider**: "One slider moves the map cells, this panel and the 48-hour chart together."

**1:20–2:10 · Activity comparison**
- Planner is at threshold **≤ 100**: "No window tomorrow meets AQI 100. The app says so in amber.
  The least-polluted slot, 15:30–16:30, is **not labelled safe**; it suggests an indoor alternative."
- Switch the threshold to **≤ 200**: "Now 15:30–16:30 is the lowest-index eligible window, with a
  **29% lower PM2.5 pollution-time index** than my planned 07:30 slot: 53.9 vs 75.9 µg·h/m³.
  It's still Unhealthy, and the app says that too."
- Point at the chart: grey is my slot, green is the alternative, the shaded band is the permitted hours.
- Open **Why this result?**: "It sums hourly PM2.5 times minutes of overlap, so partial hours count
  correctly. Windows with missing data are excluded. The explanation is generated from the numbers,
  with no AI involved, and it isn't a dose or health-risk score. Rescheduling doesn't clean the air."

**2:10–2:40 · Real AWS use**
- Switch to the CloudFormation stack: "This is deployed with AWS SAM: a Lambda function running
  FastAPI, an API Gateway HTTP API with throttling, a **private** S3 bucket served only through
  CloudFront Origin Access Control, and CloudFront routing `/api/*` to the API."
- Show CloudWatch Logs: the `/api/plan` and `/api/grid` requests made a moment ago.
- "Keys stay server-side, and there's no NAT, VPC or database. Teardown is one script."

**2:40–2:55 · Close**
- Open **Evidence & limitations**: "Every number shows its source, model, resolution, retrieval time
  and stale status. If a provider fails, you get an error rather than made-up data."
- "AirWindow helps coordinators pick the least-bad time and be honest about the forecast's limits."
