"""Capture REAL provider responses for Delhi into a replay fixture.

Usage (from backend/):  python scripts/capture_replay.py [--out fixtures/replay_delhi.json]

The output keeps the raw provider JSON, the request parameters (no API keys)
and the capture time, so replay mode can label exactly what it serves.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import load_settings  # noqa: E402
from app.providers import openaq, openmeteo as om  # noqa: E402

POINTS = [
    (28.6315, 77.2167, "Connaught Place, New Delhi"),
    (28.5660, 77.1767, "R.K. Puram, New Delhi"),
    (28.7041, 77.1025, "Pitampura, Delhi"),
    (28.5355, 77.3910, "Noida Sector 18"),
    (28.4595, 77.0266, "Gurugram"),
]
GRID_BBOX = (27.8, 76.4, 29.6, 78.0)  # south, west, north, east (Delhi NCR)
GEOCODE = ["delhi", "new delhi", "noida", "gurugram"]


async def main(out: Path) -> None:
    captured_at = datetime.now(timezone.utc).replace(microsecond=0)
    data: dict = {
        "meta": {
            "captured_at": captured_at.isoformat().replace("+00:00", "Z"),
            "synthetic": False,
            "description": "Real Open-Meteo responses for Delhi NCR captured by scripts/capture_replay.py. "
            "Replay mode serves these unchanged and treats the capture time as 'now'.",
            "sources": [om.AQ_SOURCE["provider_url"], om.WX_SOURCE["provider_url"],
                        "https://open-meteo.com/en/docs/geocoding-api"],
            "requests": [],
        },
        "points": [],
        "cells": {},
        "geocode": {},
        "stations": None,
    }
    reqs = data["meta"]["requests"]
    for lat, lon, label in POINTS:
        aq = await om.fetch_point_aq(lat, lon)
        wx = await om.fetch_point_weather(lat, lon)
        tz = await om.fetch_timezone(lat, lon)
        reqs.append(om.public_url(om.AQ_URL, om.point_aq_params(lat, lon)))
        reqs.append(om.public_url(om.WX_URL, om.point_wx_params(lat, lon)))
        data["points"].append({"lat": lat, "lon": lon, "label": label, "aq": aq, "weather": wx, "timezone": tz})
        print(f"point {label}: ok ({tz})")

    s, w, n, e = GRID_BBOX
    lats = [round(i * om.CELL_DEG, 4) for i in range(round(s / om.CELL_DEG), round(n / om.CELL_DEG) + 1)]
    lons = [round(j * om.CELL_DEG, 4) for j in range(round(w / om.CELL_DEG), round(e / om.CELL_DEG) + 1)]
    cells = [(la, lo) for la in lats for lo in lons]
    raws = await om.fetch_grid(cells)
    reqs.append(om.public_url(om.AQ_URL, om.grid_params(cells)))
    for (la, lo), raw in zip(cells, raws):
        data["cells"][om.cell_id(la, lo)] = raw
    print(f"grid: {len(cells)} cells")

    for q in GEOCODE:
        data["geocode"][q] = await om.geocode(q)

    key = load_settings().openaq_api_key or os.environ.get("OPENAQ_API_KEY", "")
    if key:
        lat, lon, _ = POINTS[0]
        data["stations"] = await openaq.fetch_nearby(lat, lon, 25_000, key)
        data["meta"]["sources"].append(openaq.SOURCE["provider_url"])
        print("stations: captured")
    else:
        print("stations: skipped (no OPENAQ_API_KEY)")

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {out} ({out.stat().st_size // 1024} KiB) captured_at={data['meta']['captured_at']}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(Path(__file__).resolve().parent.parent / "fixtures" / "replay_delhi.json"))
    asyncio.run(main(Path(ap.parse_args().out)))
