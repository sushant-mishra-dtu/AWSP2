"""End-to-end campus workflow through the HTTP API (local SQLite store, local
dev sign-in, local notifier) with SYNTHETIC Open-Meteo-shaped forecasts."""

from datetime import datetime, timezone

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.runtime import build

from .conftest import FakeClock, synthetic_hourly

T0 = 1_791_676_800 - 86_400  # 2026-10-10T00:00Z; clock is 2026-10-11T12:00Z
H = 96


def aq_payload(morning_aqi=170, afternoon_aqi=120, morning_pm=80.0, afternoon_pm=40.0, missing_hours=()):
    """SYNTHETIC: high in 00-06 UTC (05:30-11:30 IST), lower 08-12 UTC (13:30-17:30 IST)."""
    us, pm = [], []
    for i in range(H):
        h = (i % 24)
        hi = 0 <= h < 7
        if i in missing_hours:
            us.append(None); pm.append(None)
        else:
            us.append(morning_aqi if hi else afternoon_aqi)
            pm.append(morning_pm if hi else afternoon_pm)
    vars_ = {"us_aqi": us, "pm2_5": pm}
    for v in ("pm10", "nitrogen_dioxide", "ozone", "sulphur_dioxide", "carbon_monoxide"):
        vars_[v] = [10.0] * H
    for v in ("us_aqi_pm2_5", "us_aqi_pm10", "us_aqi_nitrogen_dioxide", "us_aqi_ozone", "us_aqi_sulphur_dioxide", "us_aqi_carbon_monoxide"):
        vars_[v] = us
    return synthetic_hourly(T0, H, vars_, 28.6, 77.2)


@pytest.fixture
def clock():
    return FakeClock()  # 2026-10-11T12:00:00Z = 17:30 IST


@pytest.fixture
def rt(tmp_path, clock):
    return build(Settings(data_dir=tmp_path), clock=clock)


@pytest.fixture
def api(rt):
    return TestClient(create_app(rt))


def login(api, name):
    r = api.post("/api/auth/local-login", json={"name": name})
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['token']}"}


ORG = {"name": "Demo Public School", "lat": 28.6315, "lon": 77.2167, "timezone": "Asia/Kolkata",
       "location_label": "Connaught Place, New Delhi", "threshold_aqi": 150}
PE = {"name": "Morning PE", "kind": "pe", "days": [0, 1, 2, 3, 4, 5, 6], "start": "07:30", "duration_min": 60,
      "participants": 40, "location_note": "Main field", "alternatives": [{"start": "13:30", "end": "16:00"}]}


def setup_org(api, router, payload=None, org=ORG, act=PE):
    router.add("air-quality-api.open-meteo.com", httpx.Response(200, json=payload or aq_payload()))
    h = login(api, "Coordinator A")
    o = api.post("/api/orgs", json=org, headers=h)
    assert o.status_code == 200, o.text
    oid = o.json()["org_id"]
    a = api.post(f"/api/orgs/{oid}/activities", json=act, headers=h)
    assert a.status_code == 200, a.text
    return h, oid


def tomorrow_card(api, h, oid):
    cards = api.get(f"/api/orgs/{oid}/cards", headers=h).json()["cards"]
    return next(c for c in cards if c["date"] == "2026-10-12")


def test_runtime_labels_local_mode(api):
    j = api.get("/api/runtime").json()
    assert j["store"] == "sqlite-local" and j["auth"] == "local-dev-signin" and j["notifier"] == "local-outbox"
    assert "None of this is AWS" in j["local_mode_notice"]


def test_auth_required(api):
    assert api.get("/api/orgs").status_code == 401
    assert api.post("/api/orgs", json=ORG).status_code == 401
    assert api.get("/api/orgs", headers={"Authorization": "Bearer forged.token"}).status_code == 401


def test_create_org_activity_and_timezone(api, router):
    h, oid = setup_org(api, router)
    cards = api.get(f"/api/orgs/{oid}/cards", headers=h).json()["cards"]
    # Today's 07:30 IST (02:00Z) already started; tomorrow's is upcoming.
    today = next(c for c in cards if c["date"] == "2026-10-11")
    tmr = next(c for c in cards if c["date"] == "2026-10-12")
    assert today["in_past"] is True
    assert tmr["planned"]["start_utc"] == "2026-10-12T02:00:00Z"
    assert tmr["planned"]["start_local"].startswith("2026-10-12T07:30:00+05:30")
    assert [r["label"] for r in tmr["allowed_ranges"]] == ["07:30–08:30", "13:30–16:00"]


def test_card_threshold_breach_with_alternative(api, router):
    h, oid = setup_org(api, router)
    c = tomorrow_card(api, h, oid)
    assert c["status"] == "exceeds_with_alternative" and c["exceeds"] is True
    assert c["planned"]["peak_aqi"] == 170 and c["planned_category"]["label"] == "Unhealthy"
    assert c["aqi_standard"].startswith("US AQI")
    assert c["alternative"]["meets_threshold"] is True
    assert c["comparison"]["pct_change"] == -50.0  # 80 -> 40 ug/m3 for the same 60 min
    assert c["provenance"]["spatial_resolution"] == "0.4° (~45 km)" and c["provenance"]["retrieved_at"]
    assert c["guidance"]["source"]["standard"] == "US AQI"
    assert "not an Indian government directive" in c["guidance"]["source"]["scope_note"]
    assert "unverified" in c["indoor_note"]


def test_no_eligible_alternative_is_not_safe(api, router):
    h, oid = setup_org(api, router, payload=aq_payload(morning_aqi=190, afternoon_aqi=170, afternoon_pm=60.0))
    c = tomorrow_card(api, h, oid)
    assert c["status"] == "exceeds_no_alternative"
    assert c["alternative"] is None and c["least_polluted"]["meets_threshold"] is False
    assert any("not a safe window" in line for line in c["explanation"])


def test_missing_forecast_is_unavailable_not_green(api, router):
    # Tomorrow 02:00Z is index 50 in the series (T0 = 10 Oct 00:00Z).
    h, oid = setup_org(api, router, payload=aq_payload(missing_hours=(50,)))
    c = tomorrow_card(api, h, oid)
    assert c["status"] == "data_unavailable"
    assert c["planned_category"]["key"] == "unavailable"


def test_accept_and_complete_with_audit_history(api, router):
    h, oid = setup_org(api, router)
    api.post(f"/api/orgs/{oid}/assess", headers=h)
    c = tomorrow_card(api, h, oid)
    alt = c["alternative"]
    r = api.post(f"/api/orgs/{oid}/occurrences/{c['occurrence_id']}/actions",
                 json={"type": "accept_alternative", "start_utc": alt["start_utc"]}, headers=h)
    assert r.status_code == 200, r.text
    d = r.json()["decision"]
    assert d["type"] == "accept_alternative" and d["details"]["comparison"]["pct_change"] == -50.0
    assert d["details"]["forecast_retrieved_at"]
    # Completion is a separate record and only possible once the time has started.
    assert api.post(f"/api/orgs/{oid}/occurrences/{c['occurrence_id']}/actions",
                    json={"type": "complete", "outcome": "held_as_changed"}, headers=h).status_code == 400
    today = next(x for x in api.get(f"/api/orgs/{oid}/cards", headers=h).json()["cards"] if x["date"] == "2026-10-11")
    r = api.post(f"/api/orgs/{oid}/occurrences/{today['occurrence_id']}/actions",
                 json={"type": "complete", "outcome": "held_as_planned", "note": "PE held"}, headers=h)
    assert r.status_code == 200 and r.json()["outcome"]["outcome"] == "held_as_planned"
    events = [x["event"] for x in api.get(f"/api/orgs/{oid}/history", headers=h).json()["history"]]
    for e in ("org_registered", "activity_saved", "assessment_manual", "decision_accept_alternative", "outcome_recorded"):
        assert e in events
    imp = api.get("/api/impact?scope=all").json()["counters"]
    assert imp["accepted"] == 1 and imp["completed"] == 1 and imp["participant_sessions_completed"] == 40


def test_keep_original_requires_reason_and_indoor_is_unverified(api, router):
    h, oid = setup_org(api, router)
    c = tomorrow_card(api, h, oid)
    url = f"/api/orgs/{oid}/occurrences/{c['occurrence_id']}/actions"
    assert api.post(url, json={"type": "keep_original"}, headers=h).status_code == 400
    assert api.post(url, json={"type": "keep_original", "reason": "Exam schedule fixed"}, headers=h).status_code == 200
    r = api.post(url, json={"type": "indoor_review"}, headers=h).json()
    assert "unverified" in r["decision"]["details"]["indoor_air_quality"]
    r = api.post(url, json={"type": "shorten", "duration_min": 30}, headers=h).json()
    assert r["decision"]["details"]["comparison"]["note"].startswith("Change reflects both")


def test_ownership_isolation_between_orgs(api, router):
    h_a, oid = setup_org(api, router)
    h_b = login(api, "Coordinator B")
    for method, path in [("get", f"/api/orgs/{oid}"), ("get", f"/api/orgs/{oid}/cards"), ("get", f"/api/orgs/{oid}/history"),
                         ("post", f"/api/orgs/{oid}/assess"), ("get", f"/api/orgs/{oid}/alerts"),
                         ("get", f"/api/orgs/{oid}/subscriptions"), ("get", f"/api/orgs/{oid}/reports")]:
        assert getattr(api, method)(path, headers=h_b).status_code == 404, path
    assert api.patch(f"/api/orgs/{oid}", json={"threshold_aqi": 500}, headers=h_b).status_code == 404
    assert api.post(f"/api/orgs/{oid}/activities", json=PE, headers=h_b).status_code == 404
    assert api.get("/api/orgs", headers=h_b).json()["orgs"] == []


def test_duplicate_scheduler_invocations_do_not_duplicate_alerts(api, router, rt):
    import asyncio

    h, oid = setup_org(api, router)
    first = asyncio.run(rt.alerts.assess_all("schedule"))["results"][0]
    second = asyncio.run(rt.alerts.assess_all("schedule"))["results"][0]
    third = api.post(f"/api/orgs/{oid}/assess", headers=h).json()
    assert first["alerts_created"] >= 1
    assert second["alerts_created"] == 0 and third["alerts_created"] == 0
    alerts = api.get(f"/api/orgs/{oid}/alerts", headers=h).json()["alerts"]
    assert len(alerts) == first["alerts_created"]
    a = alerts[0]
    assert a["notification"]["status"] == "not_sent_local_mode"
    for q in ("Activity affected:", "When:", "What triggered this warning:", "alternative", "What to review:"):
        assert q in a["message"]


def test_concurrent_duplicate_is_blocked_by_conditional_write(api, router, rt):
    import asyncio

    h, oid = setup_org(api, router)
    asyncio.run(rt.alerts.assess_all("schedule"))
    # Simulate a crash after the alert write but before the occurrence update.
    for occ in rt.table.query(f"ORG#{oid}", "OCC#"):
        rt.table.put({**{k: v for k, v in occ.items() if k != "last_alert"}, "version": occ["version"] + 1})
    r = asyncio.run(rt.alerts.assess_all("schedule"))["results"][0]
    assert r["alerts_created"] == 0 and r["duplicates_skipped"] >= 1


def test_changed_condition_creates_one_new_alert(api, router, rt, clock):
    import asyncio

    h, oid = setup_org(api, router)
    first = asyncio.run(rt.alerts.assess_all("schedule"))["results"][0]
    # Forecast improves: everything within the threshold -> one condition_cleared alert per alerted occurrence.
    router.routes.clear()
    router.add("air-quality-api.open-meteo.com", httpx.Response(200, json=aq_payload(morning_aqi=90, afternoon_aqi=80)))
    clock.advance(31 * 60)
    r = asyncio.run(rt.alerts.assess_all("schedule"))["results"][0]
    assert r["alerts_created"] == first["alerts_created"] >= 1
    again = asyncio.run(rt.alerts.assess_all("schedule"))["results"][0]
    assert again["alerts_created"] == 0
    kinds = sorted(a["kind"] for a in api.get(f"/api/orgs/{oid}/alerts", headers=h).json()["alerts"])
    assert "condition_cleared" in kinds


def test_provider_failure_creates_no_alerts_and_stale_is_labelled(api, router, rt, clock):
    import asyncio

    h, oid = setup_org(api, router)
    router.routes.clear()
    router.add("air-quality-api.open-meteo.com", httpx.Response(503))
    # No cached data yet in a fresh runtime for this point? It was fetched by setup? Cards not requested -> no cache.
    r = asyncio.run(rt.alerts.assess_all("schedule"))["results"][0]
    assert r["alerts_created"] == 0 and r["errors"]
    # Now succeed once, then fail after the TTL: stale data is used and labelled.
    router.routes.clear()
    router.add("air-quality-api.open-meteo.com", httpx.Response(200, json=aq_payload()), httpx.Response(503))
    asyncio.run(rt.alerts.assess_all("schedule"))
    clock.advance(45 * 60)
    c = tomorrow_card(api, h, oid)
    assert c["provenance"]["stale"] is True and c["provenance"]["cache_status"] == "stale"


def test_acknowledge_is_separate_from_publish(api, router, rt):
    import asyncio

    h, oid = setup_org(api, router)
    asyncio.run(rt.alerts.assess_all("schedule"))
    a = api.get(f"/api/orgs/{oid}/alerts", headers=h).json()["alerts"][0]
    assert a["acknowledged"] is None
    r = api.post(f"/api/orgs/{oid}/alerts/{a['alert_id']}/ack", headers=h).json()
    assert r["acknowledged"]["method"] == "in-app acknowledgement"
    imp = api.get("/api/impact?scope=all").json()["counters"]
    assert imp["alerts_acknowledged"] == 1 and imp["notifications"]["not_sent_local_mode"] >= 1
    assert imp["notifications"]["publish_accepted"] == 0


def test_local_mode_subscription_is_not_claimed(api, router):
    h, oid = setup_org(api, router)
    s = api.post(f"/api/orgs/{oid}/subscriptions", json={"email": "coordinator@example.org"}, headers=h).json()
    assert s["status"] == "unavailable_local_mode" and s["email_masked"].startswith("co•••@")
    t = api.post(f"/api/orgs/{oid}/notifications/test", headers=h).json()
    assert t["notification"]["status"] == "not_sent_local_mode"


def test_reports_workflow_and_permissions(api, router):
    h_a, oid = setup_org(api, router)
    code = api.get(f"/api/orgs/{oid}", headers=h_a).json()["join_code"]
    h_m = login(api, "Staff Member")
    assert api.post("/api/orgs/join", json={"code": code}, headers=h_m).status_code == 200
    body = {"category": "open_burning", "lat": 28.63, "lon": 77.22, "observed_at": "2026-10-11T16:45:00+05:30",
            "description": "Smoke from a pile of leaves behind the gate"}
    rep = api.post(f"/api/orgs/{oid}/reports", json=body, headers=h_m).json()
    assert rep["status"] == "submitted" and rep["verification"] == "unverified"
    rid = rep["report_id"]
    tr = f"/api/orgs/{oid}/reports/{rid}/transition"
    assert api.post(tr, json={"step": "review", "outcome": "plausible_follow_up"}, headers=h_m).status_code == 403
    assert api.post(tr, json={"step": "assign", "task": "investigate_burning", "assignee": "Facilities"}, headers=h_a).status_code == 400
    assert api.post(tr, json={"step": "review", "outcome": "plausible_follow_up"}, headers=h_a).json()["status"] == "reviewed"
    assert api.post(tr, json={"step": "assign", "task": "investigate_burning", "assignee": "Facilities"}, headers=h_a).json()["status"] == "assigned"
    assert api.post(tr, json={"step": "record_action", "note": "Staff checked; pile removed"}, headers=h_a).json()["status"] == "action_recorded"
    done = api.post(tr, json={"step": "review_resolution", "note": "Closed"}, headers=h_a).json()
    assert done["status"] == "resolution_reviewed" and "does not show that emissions were reduced" in done["resolution"]["caveat"]
    assert [x["status"] for x in done["history"]] == ["submitted", "reviewed", "assigned", "action_recorded", "resolution_reviewed"]
    # Another coordinator cannot see the report.
    h_b = login(api, "Coordinator B")
    assert api.get(f"/api/orgs/{oid}/reports", headers=h_b).status_code == 404
    imp = api.get("/api/impact?scope=all").json()["counters"]
    assert imp["reports_reviewed"] == 1 and imp["report_followup_actions"] == 1


def test_report_photo_validation_local(api, router):
    h, oid = setup_org(api, router)
    rid = api.post(f"/api/orgs/{oid}/reports", headers=h, json={
        "category": "vehicle_idling", "lat": 28.63, "lon": 77.22, "observed_at": "2026-10-11T08:00:00+05:30",
        "description": "Buses idling at the gate"}).json()["report_id"]
    base = f"/api/orgs/{oid}/reports/{rid}"
    assert api.post(f"{base}/photo-upload", json={"content_type": "application/pdf", "size": 100}, headers=h).status_code == 400
    assert api.post(f"{base}/photo-upload", json={"content_type": "image/png", "size": 6_000_000}, headers=h).status_code == 400
    t = api.post(f"{base}/photo-upload", json={"content_type": "image/png", "size": 20}, headers=h).json()
    assert t["method"] == "PUT"
    bad = api.put(t["url"], content=b"%PDF-1.4 not an image", headers={"Content-Type": "image/png"})
    assert bad.status_code == 400
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 12
    assert api.put(t["url"], content=png, headers={"Content-Type": "image/png"}).status_code == 200
    ok = api.post(f"{base}/photo-confirm", headers=h).json()
    assert ok["photo"]["size"] == 20 and "Not verified evidence" in ok["photo"]["note"]
    url = api.get(f"{base}/photo-url", headers=h).json()["url"]
    assert api.get(url).content == png
    assert api.get(url.replace("sig=", "sig=0")).status_code == 403


def test_demo_records_are_separated(tmp_path, clock, router):
    import json as _json

    fixture = {"meta": {"captured_at": "2026-10-11T12:00:00Z", "synthetic": True, "description": "SYNTHETIC test scenario",
                        "sources": ["synthetic"]},
               "points": [{"lat": 28.6315, "lon": 77.2167, "label": "Test", "aq": aq_payload(), "weather": None,
                           "timezone": "Asia/Kolkata"}], "cells": {}, "geocode": {}, "stations": None}
    p = tmp_path / "scenario.json"
    p.write_text(_json.dumps(fixture), encoding="utf-8")
    api = TestClient(create_app(build(Settings(data_dir=tmp_path, data_mode="replay", replay_file=p), clock=clock)))
    h = login(api, "Coordinator A")
    org = api.post("/api/orgs", json=ORG, headers=h).json()
    assert org["is_demo"] is True
    assert api.get("/api/impact?scope=genuine").json()["counters"]["organisations"] == 0
    assert api.get("/api/impact?scope=demo").json()["counters"]["organisations"] == 1


def test_bulletin_deterministic_and_ai_validation(api, router):
    import asyncio

    from app import bulletin as b

    h, oid = setup_org(api, router)
    c = tomorrow_card(api, h, oid)
    r = api.post(f"/api/orgs/{oid}/occurrences/{c['occurrence_id']}/bulletin", json={"lang": "hi"}, headers=h).json()
    assert "US AQI" in r["deterministic"] and "170" in r["deterministic"] and r["hindi_note"]
    f = b.facts_from_card(c)
    det = b.deterministic(f, "en")
    assert b.validate("Peak US AQI 170 at 07:30–08:30; threshold 150.", f, det) is None
    assert "number 165" in b.validate("Peak US AQI 165 at 07:30.", f, det)
    assert "time 09:15" in b.validate("Move it to 09:15.", f, det)
    assert "concentration units" in b.validate("PM2.5 index 96.0 µg/m³ at 07:30.", f, det)
    assert b.strip_meta("Peak US AQI 170." + chr(10) + "(Word count: 118)") == "Peak US AQI 170."
    assert "planned_pm25_index_ug_h_m3" not in f  # index values are never sent to a model

    class FakeHttp:
        def __init__(self, text):
            self.text = text

        async def post(self, *a, **k):
            return httpx.Response(200, json={"choices": [{"message": {"content": self.text}}]})

    good = asyncio.run(b.bulletin(c, "en", nvidia_key="k", http=FakeHttp("Morning PE 07:30–08:30: forecast peak US AQI 170.")))
    assert good["ai_status"] == "accepted" and good["ai"]["provider"] == "NVIDIA API (fallback)"
    bad = asyncio.run(b.bulletin(c, "en", nvidia_key="k", http=FakeHttp("AQI 999 tomorrow, it is safe.")))
    assert bad["ai"] is None and bad["ai_status"] == "fallback_to_deterministic"
    assert bad["ai_attempts"][0]["status"].startswith("rejected")
