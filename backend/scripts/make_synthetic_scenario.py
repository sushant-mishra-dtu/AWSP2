"""Generate a SYNTHETIC adverse-air demo scenario for Delhi.

Every value in the output is invented to produce a reproducible pattern
(high in the morning, lower in the afternoon). It is NOT real data and is
labelled ``synthetic: true`` so the app shows "REPLAY · SYNTHETIC" everywhere
it is used. Do not present it as a forecast.

Usage (from backend/): python scripts/make_synthetic_scenario.py
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

REFERENCE_NOW = datetime(2026, 10, 11, 11, 0, tzinfo=timezone.utc)  # scenario "now" = 16:30 IST
START = int(datetime(2026, 10, 10, 0, 0, tzinfo=timezone.utc).timestamp())
HOURS = 96
CAMPUS = (28.6315, 77.2167, "Connaught Place, New Delhi (synthetic scenario)")


def series() -> dict[str, list]:
    us, pm, pm10 = [], [], []
    for i in range(HOURS):
        h = i % 24  # UTC hour; IST = UTC + 5:30
        if 0 <= h < 6:      # 05:30–11:30 IST: invented morning build-up
            a, p = 178, 96.0
        elif 6 <= h < 8:    # 11:30–13:30 IST: transition
            a, p = 160, 70.0
        elif 8 <= h < 12:   # 13:30–17:30 IST: invented afternoon dip
            a, p = 128, 44.0
        else:               # evening/night
            a, p = 165, 75.0
        us.append(a)
        pm.append(p)
        pm10.append(round(p * 1.8, 1))
    return {"us_aqi": us, "pm2_5": pm, "pm10": pm10}


def payload(lat: float, lon: float) -> dict:
    s = series()
    hourly = {"time": [START + 3600 * i for i in range(HOURS)], **s}
    for v in ("nitrogen_dioxide", "ozone", "sulphur_dioxide", "carbon_monoxide"):
        hourly[v] = [None] * HOURS  # not modelled in this synthetic scenario -> shown as unavailable
    hourly["us_aqi_pm2_5"] = s["us_aqi"]
    for v in ("us_aqi_pm10", "us_aqi_nitrogen_dioxide", "us_aqi_ozone", "us_aqi_sulphur_dioxide", "us_aqi_carbon_monoxide"):
        hourly[v] = [None] * HOURS
    units = {k: ("USAQI" if k.startswith("us_aqi") else "μg/m³") for k in hourly if k != "time"}
    return {"latitude": lat, "longitude": lon, "timezone": "GMT", "utc_offset_seconds": 0, "elevation": None,
            "hourly_units": {"time": "unixtime", **units}, "hourly": hourly, "synthetic": True}


def main() -> None:
    lat, lon, label = CAMPUS
    data = {
        "meta": {
            "captured_at": REFERENCE_NOW.isoformat().replace("+00:00", "Z"),
            "synthetic": True,
            "description": "SYNTHETIC adverse-air scenario for a reproducible demo: invented values with a high morning "
                           "and a lower afternoon. Not a forecast and not real data. 'captured_at' is the scenario's "
                           "reference 'now'.",
            "sources": ["synthetic (backend/scripts/make_synthetic_scenario.py)"],
            "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        },
        "points": [{"lat": lat, "lon": lon, "label": label, "aq": payload(lat, lon), "weather": None, "timezone": "Asia/Kolkata"}],
        "cells": {"28.8,77.2": payload(28.8, 77.2)},
        "geocode": {"delhi": [{"name": "Delhi (synthetic scenario)", "lat": lat, "lon": lon, "country": "India",
                               "country_code": "IN", "admin1": "Delhi", "timezone": "Asia/Kolkata", "population": None}]},
        "stations": None,
    }
    out = Path(__file__).resolve().parent.parent / "fixtures" / "scenario_delhi_synthetic.json"
    out.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {out} (SYNTHETIC)")


if __name__ == "__main__":
    main()
