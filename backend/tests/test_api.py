"""Endpoint-level behaviour: provider errors, stale cache presentation,
grid limits, observed-station availability and replay labelling."""

import json

import httpx
import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.config import Settings
from app.replay import ReplayStore
from app.service import Service

from .conftest import FakeClock, synthetic_hourly

T0 = 1_791_676_800  # 2026-10-11T00:00:00Z
H = 96


def aq_payload(lat=28.6, lon=77.2, aqi=150, pm=60.0):
    vars_ = {v: [aqi if v.startswith("us_aqi") else pm] * H for v in [
        "us_aqi", "pm2_5", "pm10", "nitrogen_dioxide", "ozone", "sulphur_dioxide", "carbon_monoxide",
        "us_aqi_pm2_5", "us_aqi_pm10", "us_aqi_nitrogen_dioxide", "us_aqi_ozone",
        "us_aqi_sulphur_dioxide", "us_aqi_carbon_monoxide"]}
    return synthetic_hourly(T0 - 86400, H, vars_, lat, lon)


def wx_payload():
    return synthetic_hourly(T0 - 86400, H, {"temperature_2m": [25.0] * H, "relative_humidity_2m": [50] * H,
                                             "precipitation": [0] * H, "wind_speed_10m": [5] * H,
                                             "wind_direction_10m": [90] * H})


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def client(monkeypatch, clock):
    svc = Service(Settings(), None, clock=clock)
    monkeypatch.setattr(main, "service", svc)
    return TestClient(main.app)


def test_point_provider_error_returns_error_not_data(client, router):
    router.add("air-quality-api.open-meteo.com", httpx.Response(503))
    r = client.get("/api/point", params={"lat": 28.6, "lon": 77.2, "tz": "Asia/Kolkata"})
    assert r.status_code == 502
    body = r.json()
    assert body["error"]["provider"] == "Open-Meteo"
    assert "air_quality" not in body and "current" not in body
    assert "simulated" in body["message"]


def test_point_rate_limited_is_503(client, router):
    router.add("air-quality-api.open-meteo.com", httpx.Response(429))
    r = client.get("/api/point", params={"lat": 28.6, "lon": 77.2, "tz": "Asia/Kolkata"})
    assert r.status_code == 503
    assert r.json()["error"]["kind"] == "rate_limited"


def test_point_success_has_provenance(client, router):
    router.add("air-quality-api.open-meteo.com", httpx.Response(200, json=aq_payload()))
    router.add("api.open-meteo.com", httpx.Response(200, json=wx_payload()))
    r = client.get("/api/point", params={"lat": 28.61, "lon": 77.21, "tz": "Asia/Kolkata"})
    assert r.status_code == 200
    j = r.json()
    assert j["mode"] == "live"
    src = j["air_quality"]["source"]
    assert src["data_type"] == "model_forecast"
    assert src["spatial_resolution"] == "0.4° (~45 km)"
    assert src["cache"]["status"] == "miss" and src["cache"]["stale"] is False
    reading = j["current"]["readings"][0]
    for field in ("lat", "lon", "value", "units", "aqi_standard", "source", "valid_from_utc", "retrieved_at", "data_type", "resolution"):
        assert field in reading
    assert j["current"]["category"]["label"] == "Unhealthy for sensitive groups"
    assert j["location"]["timezone"] == "Asia/Kolkata"


def test_point_stale_cache_is_labelled(client, router, clock):
    router.add("air-quality-api.open-meteo.com", httpx.Response(200, json=aq_payload()), httpx.Response(503))
    router.add("api.open-meteo.com", httpx.Response(200, json=wx_payload()), httpx.Response(503))
    p = {"lat": 28.61, "lon": 77.21, "tz": "Asia/Kolkata"}
    first = client.get("/api/point", params=p).json()
    clock.advance(45 * 60)  # past the 30-minute freshness TTL
    r = client.get("/api/point", params=p)
    assert r.status_code == 200
    j = r.json()
    cache = j["air_quality"]["source"]["cache"]
    assert cache["stale"] is True and cache["status"] == "stale"
    assert cache["retrieved_at"] == first["air_quality"]["source"]["cache"]["retrieved_at"]
    assert any("Showing cached data retrieved at" in n for n in j["notes"])


def test_weather_failure_does_not_block_pollution(client, router):
    router.add("air-quality-api.open-meteo.com", httpx.Response(200, json=aq_payload()))
    router.add("api.open-meteo.com", httpx.Response(500))
    j = client.get("/api/point", params={"lat": 28.61, "lon": 77.21, "tz": "Asia/Kolkata"}).json()
    assert j["weather"] is None
    assert j["current"]["us_aqi"] == 150
    assert any("Weather context is unavailable" in n for n in j["notes"])


def test_grid_zoomed_out_requests_nothing(client, router):
    r = client.get("/api/grid", params={"south": -60, "west": -170, "north": 70, "east": 170})
    assert r.json()["status"] == "zoom_in"
    assert router.calls == []


def test_grid_batches_dedupes_and_caches(client, router):
    def respond(req):
        lats = req.url.params["latitude"].split(",")
        return httpx.Response(200, json=[synthetic_hourly(T0, 72, {"us_aqi": [120] * 72, "pm2_5": [40.0] * 72}, float(la), 0)
                                         for la in lats])
    router.add("air-quality-api.open-meteo.com", respond)
    bbox = {"south": 28.3, "west": 76.9, "north": 28.9, "east": 77.5}
    j = client.get("/api/grid", params=bbox).json()
    ids = [c["id"] for c in j["cells"]]
    assert len(ids) == len(set(ids)) == j["counts"]["cells"]
    assert len(router.calls) == 1  # one batched provider request
    assert all(c["bounds"][1][0] - c["bounds"][0][0] == pytest.approx(0.4) for c in j["cells"])
    client.get("/api/grid", params=bbox)
    assert len(router.calls) == 1  # served from cache


def test_grid_failure_marks_cells_unavailable_without_values(client, router):
    router.add("air-quality-api.open-meteo.com", httpx.Response(500))
    j = client.get("/api/grid", params={"south": 28.3, "west": 76.9, "north": 28.9, "east": 77.5}).json()
    assert j["status"] == "error"
    assert j["errors"]
    for c in j["cells"]:
        assert c["status"] == "unavailable"
        assert all(v is None for v in c["us_aqi"])


def test_stations_without_key_explains_unavailable(client, router):
    j = client.get("/api/stations", params={"lat": 28.6, "lon": 77.2}).json()
    assert j["status"] == "unavailable"
    assert "API key" in j["reason"]
    assert j["stations"] == []
    assert router.calls == []


def test_stations_with_key_reports_raw_observations(monkeypatch, router, clock):
    svc = Service(Settings(openaq_api_key="test-key"), None, clock=clock)
    monkeypatch.setattr(main, "service", svc)
    loc = {
        "id": 42, "name": "Test Station", "locality": "Delhi", "timezone": "Asia/Kolkata",
        "provider": {"id": 1, "name": "CPCB"}, "owner": {"id": 2, "name": "Owner"},
        "isMobile": False, "isMonitor": True, "instruments": [{"id": 1, "name": "Govt"}],
        "sensors": [{"id": 7, "name": "pm25 µg/m³", "parameter": {"id": 2, "name": "pm25", "units": "µg/m³", "displayName": "PM2.5"}}],
        "coordinates": {"latitude": 28.63, "longitude": 77.22}, "licenses": [],
        "datetimeLast": {"utc": "2026-10-11T11:00:00Z", "local": "2026-10-11T16:30:00+05:30"},
    }
    stale_loc = {**loc, "id": 43, "datetimeLast": {"utc": "2025-01-01T00:00:00Z", "local": None}}
    router.add("api.openaq.org/v3/locations/42/latest", httpx.Response(200, json={"results": [
        {"datetime": {"utc": "2026-10-11T11:00:00Z", "local": "2026-10-11T16:30:00+05:30"}, "value": 88.0,
         "coordinates": {"latitude": 28.63, "longitude": 77.22}, "sensorsId": 7, "locationsId": 42}]}))
    router.add("api.openaq.org/v3/locations", httpx.Response(200, json={"results": [loc, stale_loc]}))
    j = TestClient(main.app).get("/api/stations", params={"lat": 28.6, "lon": 77.2}).json()
    assert j["status"] == "ok"
    assert j["counts"]["inactive_omitted"] == 1
    s = j["stations"][0]
    assert s["provider"] == "CPCB"
    ob = s["observations"][0]
    assert ob["value"] == 88.0 and ob["units"] == "µg/m³" and ob["age_minutes"] == 60
    assert "us_aqi" not in json.dumps(s)
    assert router.calls[0].headers["X-API-Key"] == "test-key"
    assert "test-key" not in json.dumps(j)


def test_plan_invalid_input_is_400(client, router):
    router.add("air-quality-api.open-meteo.com", httpx.Response(200, json=aq_payload()))
    router.add("api.open-meteo.com", httpx.Response(200, json=wx_payload()))
    r = client.post("/api/plan", json={"lat": 28.6, "lon": 77.2, "tz": "Asia/Kolkata", "day": "2026-10-12",
                                       "allowed_start": "18:00", "allowed_end": "06:00", "duration_min": 60,
                                       "baseline_start": "07:00", "threshold_aqi": 100})
    assert r.status_code == 400


def test_plan_end_to_end_with_synthetic_series(client, router):
    router.add("air-quality-api.open-meteo.com", httpx.Response(200, json=aq_payload(aqi=140, pm=50.0)))
    router.add("api.open-meteo.com", httpx.Response(200, json=wx_payload()))
    r = client.post("/api/plan", json={"lat": 28.6, "lon": 77.2, "tz": "Asia/Kolkata", "day": "2026-10-12",
                                       "allowed_start": "06:00", "allowed_end": "12:00", "duration_min": 30,
                                       "baseline_start": "07:00", "threshold_aqi": 100})
    j = r.json()
    assert r.status_code == 200
    assert j["status"] == "no_eligible_window"
    assert j["source"]["cache"]["status"] in ("miss", "hit")
    assert j["baseline"]["pm25_index"] == pytest.approx(25.0)


def test_replay_mode_is_labelled(tmp_path, monkeypatch):
    fixture = {
        "meta": {"captured_at": "2026-10-11T10:00:00Z", "synthetic": True,
                 "description": "SYNTHETIC test fixture", "sources": ["synthetic"]},
        "points": [{"lat": 28.6, "lon": 77.2, "label": "Test", "aq": aq_payload(), "weather": wx_payload(),
                    "timezone": "Asia/Kolkata"}],
        "cells": {}, "geocode": {}, "stations": None,
    }
    path = tmp_path / "replay.json"
    path.write_text(json.dumps(fixture), encoding="utf-8")
    svc = Service(Settings(data_mode="replay"), ReplayStore.load(path))
    monkeypatch.setattr(main, "service", svc)
    c = TestClient(main.app)
    j = c.get("/api/point", params={"lat": 28.62, "lon": 77.21}).json()
    assert j["mode"] == "replay"
    assert j["replay"]["synthetic"] is True
    assert j["server_now_utc"] == "2026-10-11T10:00:00Z"
    assert c.get("/api/point", params={"lat": 10, "lon": 10}).status_code == 404
    g = c.get("/api/grid", params={"south": 28.3, "west": 76.9, "north": 28.9, "east": 77.5}).json()
    assert all(cell["status"] == "unavailable" for cell in g["cells"])
