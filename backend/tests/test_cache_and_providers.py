import asyncio

import httpx
import pytest

from app.cache import TTLCache, cached_fetch
from app.errors import ProviderError
from app.providers import openmeteo as om
from app.providers.http import get_json

from .conftest import FakeClock, synthetic_hourly


def run(coro):
    return asyncio.run(coro)


# ------------------------------------------------------------- cache
def test_cache_fresh_then_stale_then_expired():
    clock = FakeClock()
    c = TTLCache(maxsize=10, ttl_s=60, max_stale_s=600, clock=clock)
    c.set("k", 1)
    assert c.get_fresh("k").value == 1
    clock.advance(61)
    assert c.get_fresh("k") is None
    assert c.get_stale("k").value == 1
    clock.advance(600)
    assert c.get_stale("k") is None


def test_cache_is_bounded_lru():
    c = TTLCache(maxsize=3, ttl_s=60, max_stale_s=60, clock=FakeClock())
    for k in "abcd":
        c.set(k, k)
    assert len(c) == 3
    assert c.get_fresh("a") is None


def test_cached_fetch_serves_labelled_stale_on_failure():
    clock = FakeClock()
    c = TTLCache(maxsize=10, ttl_s=60, max_stale_s=3600, clock=clock)

    async def ok():
        return {"v": 1}

    async def fail():
        raise ProviderError("Open-Meteo", "timeout", "request timed out")

    v, meta = run(cached_fetch(c, "k", ok))
    assert meta["status"] == "miss" and meta["stale"] is False
    first_retrieved = meta["retrieved_at"]
    v, meta = run(cached_fetch(c, "k", fail))
    assert meta["status"] == "hit"
    clock.advance(120)
    v, meta = run(cached_fetch(c, "k", fail))
    assert v == {"v": 1}
    assert meta["status"] == "stale" and meta["stale"] is True
    assert meta["retrieved_at"] == first_retrieved
    assert "timed out" in meta["error"]
    clock.advance(4000)
    with pytest.raises(ProviderError):
        run(cached_fetch(c, "k", fail))


# ------------------------------------------------------------- http errors
def test_rate_limit_is_not_retried(router):
    router.add("air-quality-api.open-meteo.com", httpx.Response(429, json={"reason": "limit"}))
    with pytest.raises(ProviderError) as ei:
        run(get_json("Open-Meteo", om.AQ_URL))
    assert ei.value.kind == "rate_limited"
    assert len(router.calls) == 1


def test_server_error_retried_once_then_succeeds(router):
    router.add("air-quality-api.open-meteo.com", httpx.Response(502), httpx.Response(200, json={"ok": True}))
    assert run(get_json("Open-Meteo", om.AQ_URL)) == {"ok": True}
    assert len(router.calls) == 2


def test_server_error_retry_is_limited(router):
    router.add("air-quality-api.open-meteo.com", httpx.Response(503))
    with pytest.raises(ProviderError) as ei:
        run(get_json("Open-Meteo", om.AQ_URL))
    assert ei.value.kind == "http" and ei.value.status == 503
    assert len(router.calls) == 2


def test_timeout_maps_to_timeout_error(router):
    router.add("air-quality-api.open-meteo.com", httpx.ReadTimeout("slow"))
    with pytest.raises(ProviderError) as ei:
        run(get_json("Open-Meteo", om.AQ_URL))
    assert ei.value.kind == "timeout"


def test_bad_json_is_bad_response(router):
    router.add("air-quality-api.open-meteo.com", httpx.Response(200, text="<html>not json</html>"))
    with pytest.raises(ProviderError) as ei:
        run(get_json("Open-Meteo", om.AQ_URL))
    assert ei.value.kind == "bad_response"


def test_bad_request_reason_surfaces(router):
    router.add("air-quality-api.open-meteo.com", httpx.Response(400, json={"error": True, "reason": "Latitude must be in range"}))
    with pytest.raises(ProviderError) as ei:
        run(get_json("Open-Meteo", om.AQ_URL))
    assert "Latitude" in ei.value.message


def test_empty_hourly_rejected(router):
    router.add("air-quality-api.open-meteo.com", httpx.Response(200, json={"latitude": 1, "hourly": {"time": []}}))
    with pytest.raises(ProviderError) as ei:
        run(om.fetch_point_aq(1, 1))
    assert ei.value.kind == "bad_response"


# ------------------------------------------------------------- parsing
def test_parse_hourly_keeps_nulls_and_rejects_bad_values():
    raw = synthetic_hourly(1_791_720_000, 3, {"us_aqi": [10, None, "x"], "pm2_5": [1.5, float("inf"), True]})
    p = om.parse_hourly(raw, ["us_aqi", "pm2_5", "pm10"])
    assert p["series"]["us_aqi"]["values"] == [10.0, None, None]
    assert p["series"]["pm2_5"]["values"] == [1.5, None, None]
    assert p["series"]["pm10"]["values"] == [None, None, None]  # absent variable
    assert p["series"]["us_aqi"]["units"] == "USAQI"


def test_snap_lattice():
    assert om.snap(28.6139) == pytest.approx(28.8)
    assert om.snap(28.55) == pytest.approx(28.4)
    assert om.snap(77.209) == pytest.approx(77.2)
    assert om.snap(-0.15) == pytest.approx(0.0)
    assert om.snap(-0.25) == pytest.approx(-0.4)


def test_grid_params_dedupe_friendly_format():
    p = om.grid_params([(28.8, 77.2), (28.4, 77.2)])
    assert p["latitude"] == "28.8,28.4" and p["longitude"] == "77.2,77.2"
    assert p["timezone"] == "GMT" and p["timeformat"] == "unixtime" and p["domains"] == "cams_global"
