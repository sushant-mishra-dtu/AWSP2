"""Data service: combines providers, cache, replay and the pure algorithms."""

from __future__ import annotations

import math
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable
from zoneinfo import ZoneInfo

from . import planner
from .aqi import classify_us_aqi, legend
from .cache import TTLCache, cache_meta, cached_fetch
from .config import Settings
from .errors import ProviderError
from .providers import openaq, openmeteo as om
from .replay import ReplayStore

MAX_CELLS = 100
MAX_STRIDE = 4
GRID_BATCH = 50

SUB_INDICES = {
    "us_aqi_pm2_5": ("pm2_5", "PM2.5", "24-h rolling average"),
    "us_aqi_pm10": ("pm10", "PM10", "24-h rolling average"),
    "us_aqi_nitrogen_dioxide": ("nitrogen_dioxide", "NO₂", "1-h"),
    "us_aqi_ozone": ("ozone", "O₃", "max of 1-h and 8-h"),
    "us_aqi_sulphur_dioxide": ("sulphur_dioxide", "SO₂", "max of 1-h and 24-h"),
    "us_aqi_carbon_monoxide": ("carbon_monoxide", "CO", "8-h rolling average"),
}
POLLUTANT_LABELS = {
    "pm2_5": "PM2.5",
    "pm10": "PM10",
    "nitrogen_dioxide": "NO₂",
    "ozone": "O₃",
    "sulphur_dioxide": "SO₂",
    "carbon_monoxide": "CO",
}


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def iso_epoch(ts: int) -> str:
    return iso(datetime.fromtimestamp(ts, timezone.utc))


def valid_tz(name: str | None) -> str | None:
    if not name or not isinstance(name, str) or len(name) > 64:
        return None
    try:
        ZoneInfo(name)
        return name
    except Exception:  # noqa: BLE001
        return None


class Service:
    def __init__(self, settings: Settings, replay: ReplayStore | None = None, clock: Callable[[], float] = time.time):
        self.settings = settings
        self.replay = replay
        self.clock = clock
        self.point_cache = TTLCache(maxsize=256, ttl_s=30 * 60, max_stale_s=6 * 3600, clock=clock)
        self.wx_cache = TTLCache(maxsize=256, ttl_s=30 * 60, max_stale_s=6 * 3600, clock=clock)
        self.tz_cache = TTLCache(maxsize=1024, ttl_s=7 * 86400, max_stale_s=30 * 86400, clock=clock)
        self.cell_cache = TTLCache(maxsize=4000, ttl_s=30 * 60, max_stale_s=6 * 3600, clock=clock)
        self.station_cache = TTLCache(maxsize=128, ttl_s=10 * 60, max_stale_s=3 * 3600, clock=clock)
        self.geo_cache = TTLCache(maxsize=512, ttl_s=86400, max_stale_s=7 * 86400, clock=clock)

    # ------------------------------------------------------------------ basics
    @property
    def mode(self) -> str:
        return "replay" if self.replay else "live"

    def now(self) -> datetime:
        if self.replay:
            return self.replay.captured_at
        return datetime.fromtimestamp(self.clock(), timezone.utc)

    def envelope(self) -> dict[str, Any]:
        env = {"mode": self.mode, "server_now_utc": iso(self.now())}
        if self.replay:
            env["replay"] = self.replay.label()
        return env

    def health(self) -> dict[str, Any]:
        return {
            **self.envelope(),
            "status": "ok",
            "openaq_configured": self.settings.openaq_configured or bool(self.replay and self.replay.stations()),
            "legend": legend(),
            "aq_source": om.AQ_SOURCE,
            "cell_size_deg": om.CELL_DEG,
        }

    # ------------------------------------------------------------------ geocode
    async def geocode(self, q: str) -> dict[str, Any]:
        q = q.strip()
        if self.replay:
            return {**self.envelope(), "results": self.replay.geocode(q)}
        results, meta = await cached_fetch(self.geo_cache, q.lower(), lambda: om.geocode(q))
        return {**self.envelope(), "results": results, "cache": meta, "source": "Open-Meteo Geocoding API (GeoNames)"}

    # ------------------------------------------------------------------ point
    async def _point_raw(self, lat: float, lon: float, tz_hint: str | None):
        """Return (aq_raw, aq_meta, wx_raw|None, wx_meta|error, tz, tz_note)."""
        if self.replay:
            p = self.replay.point(lat, lon)
            meta = {"status": "replay", "stale": False, "retrieved_at": self.replay.meta.get("captured_at"), "error": None}
            return p["aq"], meta, p.get("weather"), meta, p.get("timezone") or "UTC", None, p

        key = (round(lat, 3), round(lon, 3))
        aq_raw, aq_meta = await cached_fetch(self.point_cache, key, lambda: om.fetch_point_aq(lat, lon))
        try:
            wx_raw, wx_meta = await cached_fetch(self.wx_cache, key, lambda: om.fetch_point_weather(lat, lon))
        except ProviderError as err:
            wx_raw, wx_meta = None, {"status": "error", "stale": False, "retrieved_at": None, "error": str(err)}
        tz, tz_note = valid_tz(tz_hint), None
        if not tz:
            try:
                tzkey = (round(lat, 2), round(lon, 2))
                tz, _ = await cached_fetch(self.tz_cache, tzkey, lambda: om.fetch_timezone(lat, lon))
                tz = valid_tz(tz) or "UTC"
            except ProviderError:
                tz, tz_note = "UTC", "Timezone lookup failed; times are shown in UTC."
        return aq_raw, aq_meta, wx_raw, wx_meta, tz, tz_note, None

    async def point(self, lat: float, lon: float, tz_hint: str | None = None) -> dict[str, Any]:
        aq_raw, aq_meta, wx_raw, wx_meta, tz, tz_note, replay_pt = await self._point_raw(lat, lon, tz_hint)
        aq = om.parse_hourly(aq_raw, om.AQ_VARS)
        now = self.now()
        times = aq["times"]
        cur = _current_index(times, now)
        mp = aq["model_point"]
        dist = (
            round(om.haversine_km(lat, lon, mp["lat"], mp["lon"]), 1)
            if isinstance(mp.get("lat"), (int, float)) and isinstance(mp.get("lon"), (int, float))
            else None
        )

        current = None
        if cur is not None:
            t0 = times[cur]
            readings = []
            for var in om.AQ_VARS:
                s = aq["series"][var]
                readings.append(
                    {
                        "parameter": var,
                        "label": POLLUTANT_LABELS.get(var) or _sub_label(var),
                        "value": s["values"][cur],
                        "units": s["units"],
                        "aqi_standard": "US AQI" if var.startswith("us_aqi") else None,
                        "valid_from_utc": iso_epoch(t0),
                        "valid_to_utc": iso_epoch(t0 + 3600),
                        "lat": mp["lat"],
                        "lon": mp["lon"],
                        "source": "Open-Meteo / CAMS Global",
                        "data_type": "model_forecast",
                        "retrieved_at": aq_meta.get("retrieved_at"),
                        "resolution": om.AQ_SOURCE["spatial_resolution"],
                    }
                )
            us = aq["series"]["us_aqi"]["values"][cur]
            current = {
                "valid_from_utc": iso_epoch(t0),
                "valid_to_utc": iso_epoch(t0 + 3600),
                "us_aqi": us,
                "category": classify_us_aqi(us).as_dict(),
                "dominant": _dominant(aq["series"], cur),
                "readings": readings,
            }

        weather = None
        if wx_raw:
            wx = om.parse_hourly(wx_raw, om.WX_VARS)
            wcur = _current_index(wx["times"], now)
            weather = {
                "times": wx["times"],
                "series": wx["series"],
                "current": None
                if wcur is None
                else {
                    "valid_from_utc": iso_epoch(wx["times"][wcur]),
                    **{v: wx["series"][v]["values"][wcur] for v in om.WX_VARS},
                    "units": {v: wx["series"][v]["units"] for v in om.WX_VARS},
                },
                "source": {**om.WX_SOURCE, "cache": wx_meta},
            }

        notes = []
        if tz_note:
            notes.append(tz_note)
        if aq_meta.get("stale"):
            notes.append(
                f"Live refresh failed ({aq_meta.get('error')}). Showing cached data retrieved at "
                f"{aq_meta.get('retrieved_at')}."
            )
        if weather is None:
            notes.append("Weather context is unavailable right now; pollution data is unaffected.")

        return {
            **self.envelope(),
            "location": {
                "requested": {"lat": lat, "lon": lon},
                "model_point": mp,
                "model_point_distance_km": dist,
                "timezone": tz,
                "replay_point": None
                if not replay_pt
                else {"lat": replay_pt["lat"], "lon": replay_pt["lon"], "label": replay_pt.get("label")},
            },
            "air_quality": {
                "times": times,
                "interval_s": 3600,
                "series": aq["series"],
                "current_index": cur,
                "source": {**om.AQ_SOURCE, "cache": aq_meta},
            },
            "current": current,
            "weather": weather,
            "notes": notes,
        }

    # ------------------------------------------------------------------ grid
    def lattice(self, s: float, w: float, n: float, e: float) -> tuple[list[tuple[float, float, float, float]], int]:
        """Return ([(lat, lon_display, lat, lon_request)], stride) for cells touching the bbox."""
        c = om.CELL_DEG
        s, n = max(-89.8, min(s, n)), min(89.8, max(s, n))
        if e < w:
            w, e = e, w
        if e - w > 360:
            raise ValueError("zoom_in")
        i0, i1 = math.ceil((s - c / 2) / c), math.floor((n + c / 2) / c)
        j0, j1 = math.ceil((w - c / 2) / c), math.floor((e + c / 2) / c)
        nlat, nlon = max(0, i1 - i0 + 1), max(0, j1 - j0 + 1)
        stride = 1
        while math.ceil(nlat / stride) * math.ceil(nlon / stride) > MAX_CELLS:
            stride += 1
            if stride > MAX_STRIDE:
                raise ValueError("zoom_in")
        def pick(a: int, b: int) -> list[int]:
            # Aligned to multiples of the stride so the sampled cells stay
            # stable while the user pans.
            r = [i for i in range(a, b + 1) if i % stride == 0]
            return r or ([a] if a <= b else [])

        cells = []
        for i in pick(i0, i1):
            for j in pick(j0, j1):
                lat = round(i * c, 4)
                lon_disp = round(j * c, 4)
                lon_req = round(((lon_disp + 180) % 360) - 180, 4)
                cells.append((lat, lon_disp, lat, lon_req))
        return cells, stride

    async def grid(self, s: float, w: float, n: float, e: float) -> dict[str, Any]:
        try:
            cells, stride = self.lattice(s, w, n, e)
        except ValueError:
            return {**self.envelope(), "status": "zoom_in", "cells": [], "times": [],
                    "message": "Zoom in to load model sample cells."}

        now = self.now()
        h0 = int(now.timestamp() // 3600 * 3600)
        times = [h0 - 3600 + k * 3600 for k in range(49)]

        out_cells: dict[str, dict[str, Any]] = {}
        misses: list[tuple[str, float, float, float]] = []
        for lat, lon_d, _, lon_r in cells:
            cid = om.cell_id(lat, lon_r)
            if self.replay:
                raw = self.replay.cell(cid)
                meta = {"status": "replay", "stale": False, "retrieved_at": self.replay.meta.get("captured_at"), "error": None}
                out_cells[cid] = self._cell_out(cid, lat, lon_d, raw, meta, times,
                                                missing_reason=None if raw else "not captured in replay fixture")
                continue
            entry = self.cell_cache.get_fresh(cid)
            if entry is not None:
                out_cells[cid] = self._cell_out(cid, lat, lon_d, entry.value, cache_meta(entry, "hit"), times)
            else:
                misses.append((cid, lat, lon_d, lon_r))

        errors = []
        for k in range(0, len(misses), GRID_BATCH):
            batch = misses[k : k + GRID_BATCH]
            try:
                raws = await om.fetch_grid([(lat, lon_r) for _, lat, _, lon_r in batch])
                for (cid, lat, lon_d, _), raw in zip(batch, raws):
                    entry = self.cell_cache.set(cid, raw)
                    out_cells[cid] = self._cell_out(cid, lat, lon_d, raw, cache_meta(entry, "miss"), times)
            except ProviderError as err:
                errors.append(err.as_dict())
                for cid, lat, lon_d, _ in batch:
                    stale = self.cell_cache.get_stale(cid)
                    if stale is not None:
                        out_cells[cid] = self._cell_out(cid, lat, lon_d, stale.value, cache_meta(stale, "stale", str(err)), times)
                    else:
                        out_cells[cid] = self._cell_out(cid, lat, lon_d, None, None, times, missing_reason=str(err))

        result_cells = list(out_cells.values())
        n_stale = sum(1 for c in result_cells if c["stale"])
        n_unavail = sum(1 for c in result_cells if c["status"] == "unavailable")
        status = "ok" if not n_unavail else ("error" if n_unavail == len(result_cells) else "partial")
        return {
            **self.envelope(),
            "status": status,
            "stride": stride,
            "cell_size_deg": om.CELL_DEG,
            "times": times,
            "cells": result_cells,
            "counts": {"cells": len(result_cells), "stale": n_stale, "unavailable": n_unavail},
            "errors": errors,
            "source": om.AQ_SOURCE,
        }

    def _cell_out(self, cid, lat, lon_d, raw, meta, times, missing_reason=None) -> dict[str, Any]:
        half = om.CELL_DEG / 2
        base = {
            "id": cid,
            "lat": lat,
            "lon": lon_d,
            "bounds": [[round(lat - half, 4), round(lon_d - half, 4)], [round(lat + half, 4), round(lon_d + half, 4)]],
        }
        if raw is None:
            return {**base, "status": "unavailable", "stale": False, "reason": missing_reason,
                    "us_aqi": [None] * len(times), "pm2_5": [None] * len(times), "retrieved_at": None, "model_point": None}
        parsed = om.parse_hourly(raw, om.GRID_VARS)
        idx = {t: i for i, t in enumerate(parsed["times"])}
        us = parsed["series"]["us_aqi"]["values"]
        pm = parsed["series"]["pm2_5"]["values"]
        return {
            **base,
            "status": "ok",
            "stale": bool(meta and meta.get("stale")),
            "retrieved_at": meta.get("retrieved_at") if meta else None,
            "cache": meta.get("status") if meta else None,
            "model_point": parsed["model_point"],
            "us_aqi": [us[idx[t]] if t in idx else None for t in times],
            "pm2_5": [pm[idx[t]] if t in idx else None for t in times],
        }

    # ------------------------------------------------------------------ stations
    async def stations(self, lat: float, lon: float, radius_km: float) -> dict[str, Any]:
        now = self.now()
        base = {**self.envelope(), "source": openaq.SOURCE}
        if self.replay:
            payload = self.replay.stations()
            if not payload:
                return {**base, "status": "unavailable", "reason": "No OpenAQ observations were captured in this replay fixture.", "stations": []}
            norm = openaq.normalise(payload, lat, lon, now)
            meta = {"status": "replay", "stale": False, "retrieved_at": self.replay.meta.get("captured_at"), "error": None}
        else:
            if not self.settings.openaq_configured:
                return {**base, "status": "unavailable",
                        "reason": "Observed-station layer is off: no OpenAQ API key is configured on the server. "
                                  "Forecast features are unaffected.",
                        "stations": []}
            radius_m = int(max(1, min(radius_km, 25)) * 1000)
            key = (round(lat, 2), round(lon, 2), radius_m)
            try:
                payload, meta = await cached_fetch(
                    self.station_cache, key,
                    lambda: openaq.fetch_nearby(lat, lon, radius_m, self.settings.openaq_api_key),
                )
            except ProviderError as err:
                return {**base, "status": "unavailable", "reason": f"OpenAQ request failed: {err.message}", "stations": [],
                        "error": err.as_dict()}
            norm = openaq.normalise(payload, lat, lon, now)
        status = "ok" if norm["stations"] else "no_active_stations"
        reason = None
        if status != "ok":
            reason = (f"No OpenAQ station within {norm['radius_km']} km reported in the last "
                      f"{norm['active_within_hours']} hours.")
        return {**base, "status": status, "reason": reason, "cache": meta, **norm}

    # ------------------------------------------------------------------ plan
    async def plan(self, req: dict[str, Any]) -> dict[str, Any]:
        lat, lon = req["lat"], req["lon"]
        aq_raw, aq_meta, _, _, tz, tz_note, _ = await self._point_raw(lat, lon, req.get("tz"))
        aq = om.parse_hourly(aq_raw, ["pm2_5", "us_aqi"])
        series = {
            datetime.fromtimestamp(t, timezone.utc): planner.SeriesPoint(pm, us)
            for t, pm, us in zip(aq["times"], aq["series"]["pm2_5"]["values"], aq["series"]["us_aqi"]["values"])
        }
        p = planner.PlanInput(
            timezone=tz,
            day=date.fromisoformat(req["day"]),
            allowed_start_min=_hm(req["allowed_start"]),
            allowed_end_min=_hm(req["allowed_end"]),
            duration_min=int(req["duration_min"]),
            baseline_start_min=_hm(req["baseline_start"]),
            threshold_aqi=int(req["threshold_aqi"]),
        )
        result = planner.plan(p, series, self.now())
        return {
            **self.envelope(),
            **result,
            "location": {"requested": {"lat": lat, "lon": lon}, "model_point": aq["model_point"], "timezone": tz},
            "source": {**om.AQ_SOURCE, "cache": aq_meta},
            "notes": [tz_note] if tz_note else [],
        }


def _hm(v: str) -> int:
    try:
        hh, mm = v.split(":")
        h, m = int(hh), int(mm)
    except (ValueError, AttributeError) as exc:
        raise planner.PlanInputError(f"invalid time {v!r}; expected HH:MM") from exc
    if not (0 <= h <= 24 and 0 <= m < 60) or (h == 24 and m):
        raise planner.PlanInputError(f"invalid time {v!r}")
    return h * 60 + m


def _current_index(times: list[int], now: datetime) -> int | None:
    ts = now.timestamp()
    for i, t in enumerate(times):
        if t <= ts < t + 3600:
            return i
    return None


def _sub_label(var: str) -> str:
    if var == "us_aqi":
        return "US AQI (overall)"
    info = SUB_INDICES.get(var)
    return f"US AQI sub-index · {info[1]}" if info else var


def _dominant(series: dict[str, Any], i: int) -> dict[str, Any] | None:
    best = None
    for var, (pol, label, avg) in SUB_INDICES.items():
        v = series.get(var, {}).get("values", [None])[i] if series.get(var) else None
        if v is None:
            continue
        if best is None or v > best["sub_index"]:
            best = {"parameter": pol, "label": label, "sub_index": v, "averaging": avg}
    return best
