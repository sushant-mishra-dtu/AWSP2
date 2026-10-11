"""OpenAQ API v3 adapter: nearby stations and their latest raw observations.

Observations are reported exactly as the provider gives them (parameter,
value, units, observation time, provider/owner/licence metadata). No AQI is
derived from them: a valid US AQI needs pollutant-specific averaging windows
(e.g. 24-hour PM2.5) that single latest values do not satisfy.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from ..errors import ProviderError
from .http import client, get_json
from .openmeteo import haversine_km

BASE = "https://api.openaq.org/v3"
PROVIDER = "OpenAQ"
MAX_RADIUS_M = 25_000  # documented maximum
MAX_DETAIL = 8  # nearest active stations whose latest values are fetched
ACTIVE_WITHIN_H = 48

SOURCE = {
    "provider": "OpenAQ API v3",
    "provider_url": "https://docs.openaq.org/",
    "data_type": "observation",
    "aqi_standard": None,
    "note": "Raw concentrations from the original station operators via OpenAQ. "
    "Not converted to US AQI and not coloured by AQI.",
}


def _parse_dt(v: Any) -> datetime | None:
    if not isinstance(v, str):
        return None
    try:
        return datetime.fromisoformat(v.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def _iso(dt: datetime | None) -> str | None:
    return None if dt is None else dt.isoformat().replace("+00:00", "Z")


async def fetch_nearby(lat: float, lon: float, radius_m: int, api_key: str) -> dict[str, Any]:
    """Return raw provider payloads: {'locations': [...], 'latest': {id: [...]}}."""
    if not api_key:
        raise ProviderError(PROVIDER, "not_configured", "OpenAQ API key not configured on the server")
    radius_m = max(1000, min(int(radius_m), MAX_RADIUS_M))
    headers = {"X-API-Key": api_key, "Accept": "application/json"}
    async with client() as http:
        raw = await get_json(
            PROVIDER,
            f"{BASE}/locations",
            {"coordinates": f"{lat:.4f},{lon:.4f}", "radius": radius_m, "limit": 100},
            headers=headers,
            http=http,
        )
        locs = raw.get("results", []) if isinstance(raw, dict) else []
        now = datetime.now(timezone.utc)
        active = []
        for loc in locs:
            last = _parse_dt((loc.get("datetimeLast") or {}).get("utc"))
            c = loc.get("coordinates") or {}
            if last and (now - last).total_seconds() <= ACTIVE_WITHIN_H * 3600 and c.get("latitude") is not None:
                active.append((haversine_km(lat, lon, c["latitude"], c["longitude"]), loc))
        active.sort(key=lambda x: x[0])
        chosen = [loc for _, loc in active[:MAX_DETAIL]]

        async def latest(loc_id: int) -> tuple[int, Any]:
            try:
                r = await get_json(PROVIDER, f"{BASE}/locations/{loc_id}/latest", {"limit": 100}, headers=headers, http=http)
                return loc_id, r.get("results", []) if isinstance(r, dict) else []
            except ProviderError as err:
                if err.kind == "rate_limited":
                    raise
                return loc_id, None

        pairs = await asyncio.gather(*(latest(int(loc["id"])) for loc in chosen))
    return {"locations": locs, "latest": {str(k): v for k, v in pairs}, "radius_m": radius_m}


def normalise(payload: dict[str, Any], lat: float, lon: float, now: datetime) -> dict[str, Any]:
    locs = payload.get("locations") or []
    latest = payload.get("latest") or {}
    stations = []
    inactive = 0
    for loc in locs:
        c = loc.get("coordinates") or {}
        if c.get("latitude") is None or c.get("longitude") is None:
            continue
        last = _parse_dt((loc.get("datetimeLast") or {}).get("utc"))
        if not last or (now - last).total_seconds() > ACTIVE_WITHIN_H * 3600:
            inactive += 1
            continue
        lid = str(loc.get("id"))
        if lid not in latest:
            continue  # beyond the nearest MAX_DETAIL active stations
        sensors = {
            s.get("id"): (s.get("parameter") or {})
            for s in (loc.get("sensors") or [])
            if isinstance(s, dict)
        }
        obs = []
        for m in latest.get(lid) or []:
            p = sensors.get(m.get("sensorsId")) or {}
            t = _parse_dt((m.get("datetime") or {}).get("utc"))
            v = m.get("value")
            if p.get("name") is None or t is None or not isinstance(v, (int, float)) or isinstance(v, bool):
                continue
            obs.append(
                {
                    "parameter": p.get("name"),
                    "display_name": p.get("displayName") or p.get("name"),
                    "units": p.get("units"),
                    "value": float(v),
                    "observed_at_utc": _iso(t),
                    "observed_at_local": (m.get("datetime") or {}).get("local"),
                    "age_minutes": round((now - t).total_seconds() / 60),
                    "sensor_id": m.get("sensorsId"),
                }
            )
        obs.sort(key=lambda o: (o["parameter"] != "pm25", o["parameter"]))
        stations.append(
            {
                "id": loc.get("id"),
                "name": loc.get("name"),
                "locality": loc.get("locality"),
                "timezone": loc.get("timezone"),
                "lat": c["latitude"],
                "lon": c["longitude"],
                "distance_km": round(haversine_km(lat, lon, c["latitude"], c["longitude"]), 2),
                "provider": (loc.get("provider") or {}).get("name"),
                "owner": (loc.get("owner") or {}).get("name"),
                "is_monitor": loc.get("isMonitor"),
                "is_mobile": loc.get("isMobile"),
                "instruments": [i.get("name") for i in (loc.get("instruments") or []) if isinstance(i, dict)],
                "licenses": [
                    {"name": li.get("name"), "attribution": (li.get("attribution") or {}).get("name")}
                    for li in (loc.get("licenses") or [])
                    if isinstance(li, dict)
                ],
                "datetime_last_utc": _iso(last),
                "latest_fetch_failed": latest.get(lid) is None,
                "observations": obs,
                "data_type": "observation",
            }
        )
    stations.sort(key=lambda s: s["distance_km"])
    return {
        "stations": stations,
        "counts": {
            "locations_in_radius": len(locs),
            "inactive_omitted": inactive,
            "shown": len(stations),
        },
        "radius_km": round((payload.get("radius_m") or MAX_RADIUS_M) / 1000, 1),
        "active_within_hours": ACTIVE_WITHIN_H,
    }
