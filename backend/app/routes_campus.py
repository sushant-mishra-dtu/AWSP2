"""HTTP routes for the school action workflow, alerts, reports and impact.

On AWS, /api/orgs* and /api/me sit behind the API Gateway Cognito JWT
authorizer; the backend additionally requires verified claims and enforces
organisation ownership on every call.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response

from . import bulletin as bulletin_mod
from . import impact as impact_mod
from .auth import User, require, resolve_user
from .errors import ProviderError
from .evidence import EvidenceError
from .service import valid_tz


def make_router(rt) -> APIRouter:
    r = APIRouter(prefix="/api")

    def user(request: Request) -> User:
        return require(resolve_user(request, rt.settings.auth_mode, rt.tokens))

    def now():
        return rt.service.now()

    async def card_for(org: dict, occ_id: str) -> dict:
        cards, _ = await rt.alerts.cards_for(org)
        card = next((c for c in cards if c["occurrence_id"] == occ_id), None)
        if not card:
            raise HTTPException(404, "Occurrence not found in the next 48 hours")
        return card

    # ---------------------------------------------------------------- runtime + auth
    @r.get("/runtime")
    async def runtime_info() -> dict[str, Any]:
        return {**rt.service.envelope(), **rt.describe()}

    @r.post("/auth/local-login")
    async def local_login(body: dict) -> dict[str, Any]:
        if rt.settings.auth_mode != "local" or not rt.tokens:
            raise HTTPException(404, "Local sign-in is disabled; use Cognito")
        token, u = rt.tokens.issue(str(body.get("name") or ""))
        return {"token": token, "user": u.as_dict(), "notice": "Local development sign-in. Not Cognito; no password."}

    @r.get("/me")
    async def me(request: Request) -> dict[str, Any]:
        u = user(request)
        return {"user": u.as_dict(), "orgs": rt.campus.list_orgs(u)}

    # ---------------------------------------------------------------- organisations
    @r.get("/orgs")
    async def list_orgs(request: Request):
        return {"orgs": rt.campus.list_orgs(user(request))}

    @r.post("/orgs")
    async def create_org(request: Request, body: dict):
        u = user(request)
        try:
            lat, lon = float(body["lat"]), float(body["lon"])
        except (KeyError, TypeError, ValueError) as exc:
            raise HTTPException(400, "Campus location (lat, lon) is required") from exc
        tz = valid_tz(body.get("timezone"))
        if not tz:
            try:
                tz = await rt.service.timezone_for(lat, lon)
            except ProviderError as exc:
                raise HTTPException(503, "Could not determine the campus timezone; enter it manually") from exc
        return rt.campus.create_org(u, body, tz, now())

    @r.get("/orgs/{org_id}")
    async def get_org(org_id: str, request: Request):
        u = user(request)
        org = rt.campus.org_for(u, org_id, role="member")
        return rt.campus.public_org(org, member=org["owner_sub"] != u.sub)

    @r.patch("/orgs/{org_id}")
    async def patch_org(org_id: str, request: Request, body: dict):
        return rt.campus.update_org(user(request), org_id, body, now())

    @r.post("/orgs/join")
    async def join(request: Request, body: dict):
        return rt.campus.join(user(request), str(body.get("code") or ""), now())

    # ---------------------------------------------------------------- activities
    @r.get("/orgs/{org_id}/activities")
    async def activities(org_id: str, request: Request):
        rt.campus.org_for(user(request), org_id)
        return {"activities": rt.campus.list_activities(org_id)}

    @r.post("/orgs/{org_id}/activities")
    async def add_activity(org_id: str, request: Request, body: dict):
        return rt.campus.save_activity(user(request), org_id, body, now())

    @r.put("/orgs/{org_id}/activities/{activity_id}")
    async def edit_activity(org_id: str, activity_id: str, request: Request, body: dict):
        u = user(request)
        rt.campus.org_for(u, org_id)
        if not rt.table.get(f"ORG#{org_id}", f"ACT#{activity_id}"):
            raise HTTPException(404, "Activity not found")
        return rt.campus.save_activity(u, org_id, body, now(), activity_id=activity_id)

    @r.delete("/orgs/{org_id}/activities/{activity_id}")
    async def delete_activity(org_id: str, activity_id: str, request: Request):
        rt.campus.remove_activity(user(request), org_id, activity_id, now())
        return {"ok": True}

    # ---------------------------------------------------------------- cards, assessment, actions
    @r.get("/orgs/{org_id}/cards")
    async def cards(org_id: str, request: Request):
        org = rt.campus.org_for(user(request), org_id)
        cards_, meta = await rt.alerts.cards_for(org)
        return {**rt.service.envelope(), "cards": cards_, "forecast": meta}

    @r.post("/orgs/{org_id}/assess")
    async def assess(org_id: str, request: Request):
        u = user(request)
        org = rt.campus.org_for(u, org_id)
        return await rt.alerts.assess_org(org, "manual", u)

    @r.post("/orgs/{org_id}/occurrences/{occ_id}/actions")
    async def action(org_id: str, occ_id: str, request: Request, body: dict):
        u = user(request)
        org = rt.campus.org_for(u, org_id)
        card = await card_for(org, occ_id)
        if not rt.campus.occurrence_item(org_id, occ_id):
            rt.campus.save_assessment(org_id, card, "on_action", now())
        occ = rt.campus.apply_action(u, org, card, body, now())
        return {k: v for k, v in occ.items() if k not in ("pk", "sk")}

    @r.post("/orgs/{org_id}/occurrences/{occ_id}/bulletin")
    async def make_bulletin(org_id: str, occ_id: str, request: Request, body: dict):
        org = rt.campus.org_for(user(request), org_id)
        card = await card_for(org, occ_id)
        s = rt.settings
        return await bulletin_mod.bulletin(card, str(body.get("lang") or "en"), s.bedrock_model_id,
                                           nvidia_key=s.nvidia_api_key, nvidia_model=s.nvidia_model)

    @r.get("/orgs/{org_id}/history")
    async def history(org_id: str, request: Request):
        rt.campus.org_for(user(request), org_id)
        return {"history": rt.campus.list_history(org_id)}

    # ---------------------------------------------------------------- alerts + notifications
    @r.get("/orgs/{org_id}/alerts")
    async def alerts(org_id: str, request: Request):
        rt.campus.org_for(user(request), org_id)
        return {"alerts": rt.alerts.list_alerts(org_id), "notifier": rt.notifier.kind}

    @r.post("/orgs/{org_id}/alerts/{alert_id}/ack")
    async def ack(org_id: str, alert_id: str, request: Request):
        u = user(request)
        return rt.alerts.acknowledge(u, rt.campus.org_for(u, org_id), alert_id, now())

    @r.get("/orgs/{org_id}/subscriptions")
    async def subs(org_id: str, request: Request, refresh: bool = Query(False)):
        rt.campus.org_for(user(request), org_id)
        return {"subscriptions": rt.alerts.list_subscriptions(org_id, refresh=refresh), "notifier": rt.notifier.kind,
                "can_send": rt.notifier.can_send}

    @r.post("/orgs/{org_id}/subscriptions")
    async def add_sub(org_id: str, request: Request, body: dict):
        u = user(request)
        return rt.alerts.add_subscription(u, rt.campus.org_for(u, org_id), str(body.get("email") or ""), now())

    @r.delete("/orgs/{org_id}/subscriptions/{sub_id}")
    async def del_sub(org_id: str, sub_id: str, request: Request):
        u = user(request)
        rt.alerts.remove_subscription(u, rt.campus.org_for(u, org_id), sub_id, now())
        return {"ok": True}

    @r.post("/orgs/{org_id}/notifications/test")
    async def test_notification(org_id: str, request: Request):
        u = user(request)
        a = rt.alerts.send_test(u, rt.campus.org_for(u, org_id), now())
        return {k: v for k, v in a.items() if k not in ("pk", "sk")}

    # ---------------------------------------------------------------- community reports
    @r.get("/orgs/{org_id}/reports")
    async def reports(org_id: str, request: Request):
        u = user(request)
        return {"reports": rt.reports.list(u, rt.campus.org_for(u, org_id, role="member"))}

    @r.post("/orgs/{org_id}/reports")
    async def new_report(org_id: str, request: Request, body: dict):
        u = user(request)
        return rt.reports.create(u, rt.campus.org_for(u, org_id, role="member"), body, now())

    @r.post("/orgs/{org_id}/reports/{report_id}/transition")
    async def transition(org_id: str, report_id: str, request: Request, body: dict):
        u = user(request)
        return rt.reports.transition(u, rt.campus.org_for(u, org_id, role="member"), report_id, body, now())

    @r.post("/orgs/{org_id}/reports/{report_id}/photo-upload")
    async def photo_upload(org_id: str, report_id: str, request: Request, body: dict):
        u = user(request)
        return rt.reports.photo_upload(u, rt.campus.org_for(u, org_id, role="member"), report_id,
                                       str(body.get("content_type") or ""), int(body.get("size") or 0))

    @r.post("/orgs/{org_id}/reports/{report_id}/photo-confirm")
    async def photo_confirm(org_id: str, report_id: str, request: Request):
        u = user(request)
        return rt.reports.photo_confirm(u, rt.campus.org_for(u, org_id, role="member"), report_id, now())

    @r.get("/orgs/{org_id}/reports/{report_id}/photo-url")
    async def photo_url(org_id: str, report_id: str, request: Request):
        u = user(request)
        return rt.reports.photo_url(u, rt.campus.org_for(u, org_id, role="member"), report_id)

    # Local-mode evidence endpoints (HMAC-signed, short-lived URLs). Absent on AWS.
    if rt.evidence.kind == "local-files":
        @r.put("/local-evidence/put")
        async def local_put(request: Request, key: str, exp: int, sig: str):
            if not rt.evidence.check_sig("put", key, exp, sig):
                raise HTTPException(403, "Upload link expired or invalid")
            body = await request.body()
            try:
                rt.evidence.store(key, request.headers.get("content-type", ""), body)
            except EvidenceError as exc:
                raise HTTPException(400, str(exc)) from exc
            return {"ok": True}

        @r.get("/local-evidence/get")
        async def local_get(key: str, exp: int, sig: str):
            if not rt.evidence.check_sig("get", key, exp, sig):
                raise HTTPException(403, "Link expired or invalid")
            from .evidence import sniff

            data = rt.evidence.read(key)
            return Response(data, media_type=sniff(data[:16]) or "application/octet-stream",
                            headers={"Cache-Control": "private, no-store"})

    # ---------------------------------------------------------------- impact (public, aggregate only)
    @r.get("/impact")
    async def impact(scope: str = Query("genuine", pattern="^(genuine|demo|all)$")):
        return {**rt.service.envelope(), **impact_mod.compute(rt.table, scope)}

    return r
