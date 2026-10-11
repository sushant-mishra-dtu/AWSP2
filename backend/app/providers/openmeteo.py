"""Open-Meteo Air Quality, Weather and Geocoding APIs (documented JSON APIs).

All pollution and weather series are requested with timezone=GMT and
timeformat=unixtime. Asking Open-Meteo for local time in a half-hour-offset
zone (e.g. Asia/Kolkata) shifts labels by 30 minutes relative to the model's
UTC time steps, so local conversion is done here with zoneinfo instead.
"""

from __future__ import annotations

import math
from typing import Any

from ..errors import ProviderError
from .http import get_json

AQ_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
WX_URL = "https://api.open-meteo.com/v1/forecast"
GEO_URL = "https://geocoding-api.open-meteo.com/v1/search"

PROVIDER = "Open-Meteo"
DOMAIN = "cams_global"
CELL_DEG = 0.4  # documented CAMS Global resolution: 0.4° (~45 km)

AQ_VARS = [
    "us_aqi",
    "pm2_5",
    "pm10",
    "nitrogen_dioxide",
    "ozone",
    "sulphur_dioxide",
    "carbon_monoxide",
    "us_aqi_pm2_5",
    "us_aqi_pm10",
    "us_aqi_nitrogen_dioxide",
    "us_aqi_ozone",
    "us_aqi_sulphur_dioxide",
    "us_aqi_carbon_monoxide",
]
GRID_VARS = ["us_aqi", "pm2_5"]
WX_VARS = [
    "temperature_2m",
    "relative_humidity_2m",
    "precipitation",
    "wind_speed_10m",
    "wind_direction_10m",
]

AQ_SOURCE = {
    "provider": "Open-Meteo Air Quality API",
    "provider_url": "https://open-meteo.com/en/docs/air-quality-api",
    "model": "CAMS Global atmospheric composition forecast (Copernicus/ECMWF)",
    "domain": DOMAIN,
    "data_type": "model_forecast",
    "aqi_standard": "US AQI (calculated by Open-Meteo from modelled concentrations)",
    "aqi_averaging": "PM2.5 and PM10 sub-indices use 24-hour rolling averages; "
    "O3 max(1h, 8h); CO 8h; SO2 max(1h, 24h); NO2 1h (provider documentation)",
    "spatial_resolution": "0.4° (~45 km)",
    "spatial_resolution_deg": CELL_DEG,
    "native_time_step": "3-hourly model output (provider documentation); values served hourly",
    "update_frequency": "every 12 hours (provider documentation)",
    "attribution": "Contains modified Copernicus Atmosphere Monitoring Service information; "
    "air quality data by Open-Meteo.com (CC BY 4.0)",
    "licence": "CC BY 4.0 (Open-Meteo data)",
}
WX_SOURCE = {
    "provider": "Open-Meteo Forecast API",
    "provider_url": "https://open-meteo.com/en/docs",
    "model": "Open-Meteo best-match weather models",
    "data_type": "model_forecast",
    "role": "context only — not used in AQI or the planning index",
    "attribution": "Weather data by Open-Meteo.com (CC BY 4.0)",
    "licence": "CC BY 4.0",
}


def snap(v: float) -> float:
    """Snap a coordinate to the 0.4° sampling lattice (multiples of 0.4°)."""
    return round(round(v / CELL_DEG) * CELL_DEG, 4)


def cell_id(lat: float, lon: float) -> str:
    return f"{lat:.1f},{lon:.1f}"


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def public_url(url: str, params: dict[str, Any]) -> str:
    """Request URL for provenance display (Open-Meteo free API uses no key)."""
    from urllib.parse import urlencode

    return f"{url}?{urlencode(params)}"


def point_aq_params(lat: float, lon: float) -> dict[str, Any]:
    return {
        "latitude": f"{lat:.4f}",
        "longitude": f"{lon:.4f}",
        "hourly": ",".join(AQ_VARS),
        "past_days": 1,
        "forecast_days": 3,
        "domains": DOMAIN,
        "timezone": "GMT",
        "timeformat": "unixtime",
    }


def point_wx_params(lat: float, lon: float) -> dict[str, Any]:
    return {
        "latitude": f"{lat:.4f}",
        "longitude": f"{lon:.4f}",
        "hourly": ",".join(WX_VARS),
        "past_days": 1,
        "forecast_days": 3,
        "wind_speed_unit": "kmh",
        "timezone": "GMT",
        "timeformat": "unixtime",
    }


def tz_params(lat: float, lon: float) -> dict[str, Any]:
    return {
        "latitude": f"{lat:.4f}",
        "longitude": f"{lon:.4f}",
        "current": "is_day",
        "forecast_days": 1,
        "timezone": "auto",
    }


def grid_params(cells: list[tuple[float, float]]) -> dict[str, Any]:
    return {
        "latitude": ",".join(f"{la:.1f}" for la, _ in cells),
        "longitude": ",".join(f"{lo:.1f}" for _, lo in cells),
        "hourly": ",".join(GRID_VARS),
        "past_hours": 1,
        "forecast_hours": 48,
        "domains": DOMAIN,
        "timezone": "GMT",
        "timeformat": "unixtime",
    }


async def fetch_point_aq(lat: float, lon: float) -> dict[str, Any]:
    raw = await get_json(PROVIDER, AQ_URL, point_aq_params(lat, lon))
    _check_hourly(raw, "air quality")
    return raw


async def fetch_point_weather(lat: float, lon: float) -> dict[str, Any]:
    raw = await get_json(PROVIDER, WX_URL, point_wx_params(lat, lon))
    _check_hourly(raw, "weather")
    return raw


async def fetch_timezone(lat: float, lon: float) -> str:
    raw = await get_json(PROVIDER, WX_URL, tz_params(lat, lon))
    tz = raw.get("timezone") if isinstance(raw, dict) else None
    if not tz or not isinstance(tz, str):
        raise ProviderError(PROVIDER, "bad_response", "timezone missing from response")
    return tz


async def fetch_grid(cells: list[tuple[float, float]]) -> list[dict[str, Any]]:
    if not cells:
        return []
    raw = await get_json(PROVIDER, AQ_URL, grid_params(cells))
    items = raw if isinstance(raw, list) else [raw]
    if len(items) != len(cells):
        raise ProviderError(PROVIDER, "bad_response", "grid response size mismatch")
    for it in items:
        _check_hourly(it, "grid")
    return items


async def geocode(q: str, count: int = 6) -> list[dict[str, Any]]:
    raw = await get_json(
        PROVIDER, GEO_URL, {"name": q, "count": count, "language": "en", "format": "json"}
    )
    out = []
    for r in (raw or {}).get("results", []) or []:
        try:
            out.append(
                {
                    "name": r["name"],
                    "lat": float(r["latitude"]),
                    "lon": float(r["longitude"]),
                    "country": r.get("country"),
                    "country_code": r.get("country_code"),
                    "admin1": r.get("admin1"),
                    "timezone": r.get("timezone"),
                    "population": r.get("population"),
                }
            )
        except (KeyError, TypeError, ValueError):
            continue
    return out


def _check_hourly(raw: Any, what: str) -> None:
    if not isinstance(raw, dict):
        raise ProviderError(PROVIDER, "bad_response", f"{what} response is not an object")
    if raw.get("error"):
        raise ProviderError(PROVIDER, "http", str(raw.get("reason") or "provider error"))
    h = raw.get("hourly")
    if not isinstance(h, dict) or not isinstance(h.get("time"), list) or not h["time"]:
        raise ProviderError(PROVIDER, "bad_response", f"{what} response has no hourly data")


def _clean(v: Any) -> float | None:
    if v is None or isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    f = float(v)
    return f if math.isfinite(f) else None


def parse_hourly(raw: dict[str, Any], variables: list[str]) -> dict[str, Any]:
    """Normalise one Open-Meteo hourly response into a columnar series."""
    h = raw["hourly"]
    times = [int(t) for t in h["time"]]
    units = raw.get("hourly_units", {}) or {}
    series = {}
    for var in variables:
        vals = h.get(var)
        if not isinstance(vals, list) or len(vals) != len(times):
            vals = [None] * len(times)
        series[var] = {"units": units.get(var), "values": [_clean(v) for v in vals]}
    return {
        "times": times,
        "interval_s": 3600,
        "model_point": {"lat": raw.get("latitude"), "lon": raw.get("longitude")},
        "elevation_m": raw.get("elevation"),
        "series": series,
    }
