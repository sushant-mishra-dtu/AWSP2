# Third-party notices

AirWindow's application code (everything under `backend/app`, `backend/tests`, `backend/scripts`,
`frontend/src`, `infra/` and `scripts/`) was written for this project. **No source code was copied
from other AQI applications.** The reference projects named in the brief
([AirAtlas](https://github.com/sarvesh-tewari/AirAtlas),
[OpenAQ Explorer](https://github.com/openaq/openaq-explorer),
[air-quality-dashboard](https://github.com/monalishanayak02/air-quality-dashboard)) were not
cloned, vendored or adapted. In particular, the dashboard's simulated fallback data behaviour
was **not** carried over: failed requests return explicit errors or labelled stale cache entries.

Licence identifiers below were read from each installed package's own metadata
(`package.json` / Python distribution metadata) on 2026-10-11. Full licence texts ship inside
each package (`frontend/node_modules/<pkg>/LICENSE*`, Python `*.dist-info/`).

## Frontend runtime dependencies (bundled into the built site)

| Package | Version | Licence | Notes |
|---|---|---|---|
| [Leaflet](https://github.com/Leaflet/Leaflet) | 1.9.4 | BSD-2-Clause | © 2010–2023 Volodymyr Agafonkin, © 2010–2011 CloudMade |
| [React](https://github.com/facebook/react) / react-dom / react-is | 19.3.0 | MIT | © Meta Platforms, Inc. and affiliates |
| [react-leaflet](https://github.com/PaulLeCam/react-leaflet) / @react-leaflet/core | 5.0.0 / 3.0.0 | **Hippocratic License 2.1** | © Paul Le Cam. Ethical-source licence (not OSI-approved); permits this use subject to its human-rights conditions. If an OSI-only policy applies, `MapView.tsx` can be ported to plain Leaflet. |
| [Recharts](https://github.com/recharts/recharts) | 3.10.1 | MIT | © Recharts Group |
| Recharts dependencies: @reduxjs/toolkit, react-redux, reselect, immer, clsx, decimal.js-light, es-toolkit, eventemitter3, tiny-invariant, use-sync-external-store | various | MIT | |
| victory-vendor (Recharts dependency; re-exports d3 modules) | 37.3.6 | MIT AND ISC | d3 modules © Mike Bostock (ISC) |

Build-only tools (not shipped): Vite (MIT), @vitejs/plugin-react (MIT), Tailwind CSS and
@tailwindcss/vite (MIT), TypeScript (Apache-2.0), Vitest (MIT), @types/* (MIT).

Fonts: Inter and JetBrains Mono, loaded from Google Fonts (SIL Open Font License 1.1).

## Backend runtime dependencies (packaged into the Lambda function)

| Package | Version | Licence |
|---|---|---|
| FastAPI | 0.143.0 | MIT |
| Starlette | 1.7.0 | BSD-3-Clause |
| Pydantic / pydantic-core | 2.14.0 / 2.50.0 | MIT |
| Mangum | 0.22.0 | MIT |
| HTTPX / httpcore | 0.28.1 / 1.0.9 | BSD-3-Clause |
| AnyIO, h11, annotated-types, typing-inspection, annotated-doc | various | MIT |
| idna | 3.20 | BSD-3-Clause |
| certifi | 2026.7.22 | MPL-2.0 |
| tzdata | 2026.5 | Apache-2.0 |
| typing_extensions | 4.16.0 | PSF-2.0 |
| opentelemetry-api (transitive) | 1.45.1 | Apache-2.0 |

AWS SDK: boto3 / botocore / s3transfer 1.43.x (Apache-2.0), with jmespath (MIT), python-dateutil
(Apache-2.0/BSD dual) and urllib3 (MIT). On Lambda the runtime-provided boto3 is used; the pinned
version is used locally and in tests.

Dev/deploy/test tools (not shipped): uvicorn (BSD-3-Clause), pytest (MIT), AWS SAM CLI (Apache-2.0),
**moto 5.2.3 (Apache-2.0), a local AWS API emulator used only in tests** (it is not AWS; see README §4).

## Data and map services

| Service | Use in AirWindow | Terms / attribution |
|---|---|---|
| [Open-Meteo Air Quality API](https://open-meteo.com/en/docs/air-quality-api) | Modelled pollutants and provider-calculated US AQI (`domains=cams_global`) | Open-Meteo data CC BY 4.0; free API for non-commercial use. Contains modified Copernicus Atmosphere Monitoring Service information. Neither the European Commission nor ECMWF is responsible for any use of this information. |
| [Open-Meteo Forecast API](https://open-meteo.com/en/docs) | Weather context (temperature, humidity, wind, precipitation) and timezone lookup | CC BY 4.0 |
| [Open-Meteo Geocoding API](https://open-meteo.com/en/docs/geocoding-api) | Place search | CC BY 4.0; based on GeoNames (CC BY 4.0) |
| [OpenAQ API v3](https://docs.openaq.org/) (optional) | Nearby station observations | OpenAQ platform terms; each location's data licence/attribution is returned by the API and shown per station |
| [OpenStreetMap](https://www.openstreetmap.org/copyright) standard tiles | Base map | Map data © OpenStreetMap contributors (ODbL); tiles used under the OSMF Tile Usage Policy with attribution |
| [AirNow / U.S. EPA school guidance](https://www.airnow.gov/publications/air-quality-flag-program-getting-started/air-quality-and-outdoor-activity-guidance-for-schools-flag-program/) | Per-category outdoor-activity guidance shown on action cards and in bulletins | U.S. government work (EPA-456/F-14-003, Aug 2014). Paraphrased with source link; labelled US-AQI guidance, not an Indian directive |
| [NVIDIA API catalog](https://build.nvidia.com/) (optional) | Fallback wording/translation of coordinator bulletins (`nvidia/nemotron-3-super-120b-a12b`) | NVIDIA API terms of service. Only the bulletin fact summary is sent; output is validated and shown separately as AI-worded |
| Amazon Bedrock (optional) | Primary wording/translation of bulletins when a model id is configured | AWS Service Terms and the chosen model's terms |

Hindi bulletin templates in `backend/app/bulletin.py` were translated with AI assistance (see README §9).

Attribution for Open-Meteo/CAMS and OpenStreetMap is shown in the map's attribution control,
the app footer and the "Evidence & limitations" panel.
