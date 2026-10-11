"""Shared test helpers.

All provider payloads built here are SYNTHETIC test data shaped like the
documented Open-Meteo / OpenAQ responses. They are never used by the app's
live or replay modes.
"""

from __future__ import annotations

import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.providers import http as http_mod  # noqa: E402


class FakeClock:
    def __init__(self, t: float = 1_791_720_000.0):  # 2026-10-11T12:00:00Z
        self.t = t

    def __call__(self) -> float:
        return self.t

    def advance(self, s: float) -> None:
        self.t += s


def synthetic_hourly(t0: int, hours: int, variables: dict[str, list], lat=28.6, lon=77.2) -> dict:
    """SYNTHETIC Open-Meteo-shaped hourly payload (GMT + unixtime)."""
    hourly = {"time": [t0 + 3600 * i for i in range(hours)]}
    units = {"time": "unixtime"}
    for k, vals in variables.items():
        assert len(vals) == hours
        hourly[k] = vals
        units[k] = "USAQI" if k.startswith("us_aqi") else "μg/m³"
    return {
        "latitude": lat,
        "longitude": lon,
        "utc_offset_seconds": 0,
        "timezone": "GMT",
        "hourly_units": units,
        "hourly": hourly,
    }


class Router:
    """Records calls and returns queued responses per host+path prefix."""

    def __init__(self):
        self.routes: list[tuple[str, list]] = []
        self.calls: list[httpx.Request] = []

    def add(self, prefix: str, *responses):
        self.routes.append((prefix, list(responses)))

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        url = f"{request.url.host}{request.url.path}"
        for prefix, queue in self.routes:
            if url.startswith(prefix):
                if not queue:
                    raise AssertionError(f"no response queued for {url}")
                item = queue.pop(0) if len(queue) > 1 else queue[0]
                if isinstance(item, Exception):
                    raise item
                if callable(item):
                    return item(request)
                return item
        raise AssertionError(f"unexpected request {url}")


@pytest.fixture
def router():
    r = Router()
    http_mod.set_transport(httpx.MockTransport(r))
    yield r
    http_mod.set_transport(None)


@pytest.fixture(autouse=True)
def fast_backoff(monkeypatch):
    import asyncio

    real_sleep = asyncio.sleep

    async def no_sleep(_s):
        await real_sleep(0)

    monkeypatch.setattr(http_mod.asyncio, "sleep", no_sleep)
