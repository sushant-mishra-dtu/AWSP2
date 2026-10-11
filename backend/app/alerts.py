"""Advance warnings: scheduled (EventBridge Scheduler -> Lambda) and manual
("Check upcoming activities now") assessments share ``assess_org``.

De-duplication: an alert's id is a hash of (occurrence, previous condition
fingerprint, new fingerprint) and is written with a conditional put, so
repeated or concurrent invocations for an unchanged activity and forecast
condition never create a second alert. A cooldown limits how often one
occurrence can trigger an email. Failed publishes are retried on later runs
(max 3 attempts). Nothing here claims exactly-once email delivery.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import HTTPException

from .auth import User
from .campus import Campus, now_iso
from .errors import ProviderError
from .guidance import INDOOR_NOTE
from .guidance import SOURCE as GUIDANCE_SOURCE
from .guidance import for_category
from .notify import EMAIL_RE, NotifyError, mask_email
from .store import ConditionFailed, Table

COOLDOWN = timedelta(minutes=int(os.environ.get("ALERT_COOLDOWN_MIN", "120")))
MAX_PUBLISH_ATTEMPTS = 3
MAX_ORGS_PER_RUN = int(os.environ.get("MAX_ORGS_PER_RUN", "10"))
SKIP_ALERT_DECISIONS = {"cancel", "postpone"}


def fingerprint(card: dict) -> str:
    """Discretised condition: changes only when the recommendation changes materially."""
    if card["status"] == "data_unavailable":
        return "data_unavailable"
    alt = card["alternative"] or card["least_polluted"]
    alt_hour = alt["start_utc"][:13] if alt else "none"  # recommendation moved by >= 1 hour bucket
    return f"{card['status']}|{card['planned_category']['key']}|{alt_hour}"


def alert_kind(card: dict, prev: dict | None) -> str | None:
    fp = fingerprint(card)
    if card["status"] == "data_unavailable":
        return None
    if prev is None:
        return "threshold_exceeded" if card["exceeds"] else None
    if fp == prev.get("fingerprint"):
        return None
    if card["exceeds"]:
        return "recommendation_changed"
    if prev.get("kind") != "condition_cleared":
        return "condition_cleared"
    return None


def emit_metrics(namespace: str, dims: dict[str, str], metrics: dict[str, float]) -> None:
    """CloudWatch Embedded Metric Format: one JSON log line becomes metrics (no extra IAM)."""
    print(json.dumps({
        "_aws": {"Timestamp": int(time.time() * 1000), "CloudWatchMetrics": [{
            "Namespace": namespace, "Dimensions": [list(dims.keys())],
            "Metrics": [{"Name": k, "Unit": "Count"} for k in metrics]}]},
        **dims, **metrics,
    }))


class Alerts:
    def __init__(self, table: Table, campus: Campus, notifier, service, app_url: str = ""):
        self.t = table
        self.campus = campus
        self.notifier = notifier
        self.svc = service
        self.app_url = app_url.rstrip("/")

    # ------------------------------------------------------------------ assessment
    async def cards_for(self, org: dict, now: datetime | None = None) -> tuple[list[dict], dict]:
        now = now or self.svc.now()
        series, meta, mode_info = await self.svc.campus_series(org["lat"], org["lon"], org["timezone"])
        acts = self.campus.list_activities(org["org_id"])
        cards = [self.campus.build_card(org, o, series, meta, now, mode_info) for o in self.campus.occurrences(org, acts, now)]
        return cards, {**meta, **mode_info}

    async def assess_org(self, org: dict, trigger: str, user: User | None = None) -> dict:
        now = self.svc.now()
        summary: dict[str, Any] = {"org_id": org["org_id"], "trigger": trigger, "at": now_iso(now), "assessed": 0,
                                   "alerts_created": 0, "duplicates_skipped": 0, "notifications": {}, "retried": 0, "errors": []}
        try:
            cards, meta = await self.cards_for(org, now)
        except ProviderError as err:
            summary["errors"].append(f"forecast unavailable: {err.message}")
            return summary
        summary["forecast"] = {k: meta.get(k) for k in ("retrieved_at", "status", "stale", "mode", "replay_captured_at", "replay_synthetic")}
        for card in cards:
            occ = self.campus.save_assessment(org["org_id"], card, trigger, now)
            summary["assessed"] += 1
            if card["in_past"] or (occ.get("decision") or {}).get("type") in SKIP_ALERT_DECISIONS:
                continue
            prev = occ.get("last_alert")
            kind = alert_kind(card, prev)
            if not kind:
                continue
            fp = fingerprint(card)
            alert_id = hashlib.sha256(f"{card['occurrence_id']}|{(prev or {}).get('fingerprint')}|{fp}".encode()).hexdigest()[:16]
            alert = self._alert_item(org, card, kind, fp, alert_id, trigger, now, meta)
            try:
                self.t.put(alert, if_not_exists=True)
            except ConditionFailed:
                summary["duplicates_skipped"] += 1
                self._set_last_alert(org["org_id"], card["occurrence_id"], {"fingerprint": fp, "kind": kind, "alert_id": alert_id, "at": now_iso(now)})
                continue
            summary["alerts_created"] += 1
            self._set_last_alert(org["org_id"], card["occurrence_id"], {"fingerprint": fp, "kind": kind, "alert_id": alert_id, "at": now_iso(now)})
            self.campus.history(org["org_id"], user, "alert_created", now,
                                {"alert_id": alert_id, "kind": kind, "occurrence_id": card["occurrence_id"], "trigger": trigger})
            status = self._notify(org, alert, occ, now)
            summary["notifications"][status] = summary["notifications"].get(status, 0) + 1
        summary["retried"] = self._retry_failed(org, now)
        if trigger == "manual" or summary["alerts_created"]:
            self.campus.history(org["org_id"], user, f"assessment_{trigger}", now,
                                {k: summary[k] for k in ("assessed", "alerts_created", "duplicates_skipped", "retried")})
        emit_metrics("AirWindow", {"Trigger": trigger}, {
            "OccurrencesAssessed": summary["assessed"], "AlertsCreated": summary["alerts_created"],
            "DuplicateAlertsSkipped": summary["duplicates_skipped"],
            "PublishAccepted": summary["notifications"].get("publish_accepted", 0),
            "PublishFailed": summary["notifications"].get("failed", 0),
        })
        return summary

    async def assess_all(self, trigger: str = "schedule") -> dict:
        watch = [x.strip() for x in os.environ.get("WATCHLIST_ORG_IDS", "").split(",") if x.strip()]
        orgs = [o for o in self.t.query("ENTITY#ORG", "", index="gsi2") if not watch or o["org_id"] in watch][:MAX_ORGS_PER_RUN]
        results = []
        for org in orgs:
            try:
                results.append(await self.assess_org(org, trigger))
            except Exception as exc:  # noqa: BLE001 - one organisation must not stop the run
                results.append({"org_id": org["org_id"], "errors": [f"{exc.__class__.__name__}: {exc}"]})
        return {"trigger": trigger, "orgs": len(orgs), "results": results}

    def _set_last_alert(self, org_id: str, occ_id: str, last: dict) -> None:
        self.campus._update_occurrence(org_id, occ_id, lambda o: {**o, "last_alert": last})

    def _alert_item(self, org, card, kind, fp, alert_id, trigger, now, meta) -> dict:
        alt = card["alternative"] or card["least_polluted"]
        subject, message = self.compose(org, card, kind)
        return {
            "pk": f"ORG#{org['org_id']}", "sk": f"ALERT#{alert_id}", "type": "alert", "alert_id": alert_id,
            "kind": kind, "fingerprint": fp, "trigger": trigger, "created_at": now_iso(now),
            "occurrence_id": card["occurrence_id"], "activity_name": card["activity"]["name"],
            "planned_label": card["planned"]["label"], "planned_start_utc": card["planned"]["start_utc"],
            "date": card["date"], "status": card["status"], "threshold_aqi": card["threshold_aqi"],
            "planned_peak_aqi": card["planned"]["peak_aqi"], "planned_category": card["planned_category"]["label"],
            "planned_index": card["planned"]["pm25_index"],
            "alternative": None if not alt else {"label": alt["label"], "start_utc": alt["start_utc"], "peak_aqi": alt["peak_aqi"],
                                                 "eligible": alt["eligible"], "pm25_index": alt["pm25_index"]},
            "comparison": card["comparison"], "evidence": card["provenance"],
            "is_demo": org.get("is_demo", False),
            "subject": subject, "message": message,
            "notification": {"status": "prepared", "attempts": 0, "message_id": None, "last_error": None, "published_at": None},
            "acknowledged": None,
        }

    # ------------------------------------------------------------------ message
    def compose(self, org: dict, card: dict, kind: str) -> tuple[str, str]:
        tz = ZoneInfo(org["timezone"])
        start = datetime.fromisoformat(card["planned"]["start_utc"].replace("Z", "+00:00")).astimezone(tz)
        when = f"{start:%a %d %b} {card['planned']['label']} ({start.tzname()})"
        cat = card["planned_category"]["label"]
        a = card["activity"]
        prov = card["provenance"]
        heading = {"threshold_exceeded": "Forecast exceeds your threshold",
                   "recommendation_changed": "Recommendation changed",
                   "condition_cleared": "Forecast now within your threshold"}[kind]
        subject = f"AirWindow: {heading} - {a['name']} {when}"
        alt = card["alternative"]
        if alt:
            pct = f", {card['comparison']['pct_change']:+.1f}% PM2.5 index" if card.get("comparison") else ""
            alt_line = f"Lower-pollution alternative: {alt['label']} (peak US AQI {alt['peak_aqi']}{pct})."
        elif card["least_polluted"]:
            lp = card["least_polluted"]
            alt_line = (f"No permitted time meets your threshold. Least-polluted permitted time {lp['label']} (peak US AQI "
                        f"{lp['peak_aqi']}) still exceeds it - it is not a safe window. Consider an indoor option, "
                        f"postponing or cancelling.")
        else:
            alt_line = "No change needed at the planned time." if not card["exceeds"] else "No complete alternative window is available."
        g = for_category(card["planned_category"]["key"])
        notes = []
        if prov.get("stale"):
            notes.append("NOTE: live refresh failed; this uses cached forecast data.")
        if prov.get("mode") == "replay":
            notes.append(f"DEMO: replay data captured {prov.get('replay_captured_at')}"
                         + (" (SYNTHETIC scenario)" if prov.get("replay_synthetic") else "") + ".")
        lines = [
            f"AirWindow advance warning for {org['name']}" + (" [DEMO RECORD]" if org.get("is_demo") else ""),
            *notes,
            "",
            f"Activity affected: {a['name']}" + (f" ({a['location_note']})" if a.get("location_note") else "")
            + f", about {a['participants']} participants (coordinator estimate).",
            f"When: {when}.",
            "",
            "What triggered this warning:",
            f"- Forecast peak US AQI {card['planned']['peak_aqi']} ({cat}) during the planned time; your planning threshold is {card['threshold_aqi']}.",
            f"- Forecast PM2.5 pollution-time index {card['planned']['pm25_index']:.1f} ug*h/m3." if card["planned"]["pm25_index"] is not None else "- PM2.5 index unavailable.",
            f"- Data: {prov['source']} ({prov['model']}), modelled forecast at ~45 km resolution, valid "
            f"{prov['valid_from_utc']} to {prov['valid_to_utc']}, retrieved {prov['retrieved_at']}.",
            "",
            alt_line,
            "",
            "What to review:",
            f"- Open the action card in AirWindow{(': ' + self.app_url) if self.app_url else ''} and record a decision.",
            f"- {GUIDANCE_SOURCE['publisher']} US-AQI school guidance for '{cat}': {g['text']}",
            f"  ({GUIDANCE_SOURCE['scope_note']})",
            f"- {INDOOR_NOTE}",
            "",
            "This is a modelled forecast, not a local measurement. Sending this email does not confirm it was read - "
            "please acknowledge the warning in AirWindow.",
        ]
        return subject, "\n".join(lines)

    # ------------------------------------------------------------------ notifications
    def _notify(self, org: dict, alert: dict, occ: dict, now: datetime, ignore_cooldown: bool = False) -> str:
        n = dict(alert["notification"])
        if not self.notifier.can_send:
            n["status"] = "not_sent_local_mode"
            n["last_error"] = "Local mode: SNS is not configured; the message was prepared but not sent."
        elif not ignore_cooldown and occ.get("last_notified_at") and \
                now - datetime.fromisoformat(occ["last_notified_at"].replace("Z", "+00:00")) < COOLDOWN:
            n["status"] = "suppressed_cooldown"
        elif not self.confirmed_subscriptions(org["org_id"]):
            n["status"] = "no_confirmed_subscribers"
        else:
            n = self._publish(org, alert, n, now)
            if n["status"] == "publish_accepted" and alert.get("occurrence_id"):
                self.campus._update_occurrence(org["org_id"], alert["occurrence_id"], lambda o: {**o, "last_notified_at": now_iso(now)})
        self.t.put({**alert, "notification": n})
        return n["status"]

    def _publish(self, org: dict, alert: dict, n: dict, now: datetime) -> dict:
        n = {**n, "attempts": n.get("attempts", 0) + 1}
        try:
            n["message_id"] = self.notifier.publish(org["org_id"], alert["subject"], alert["message"], {"kind": alert["kind"]})
            n["status"] = "publish_accepted"
            n["published_at"] = now_iso(now)
            n["last_error"] = None
        except NotifyError as exc:
            n["status"] = "failed"
            n["last_error"] = str(exc)
        return n

    def _retry_failed(self, org: dict, now: datetime) -> int:
        count = 0
        for a in self.t.query(f"ORG#{org['org_id']}", "ALERT#"):
            n = a.get("notification") or {}
            if n.get("status") == "failed" and n.get("attempts", 0) < MAX_PUBLISH_ATTEMPTS and self.notifier.can_send:
                self.t.put({**a, "notification": self._publish(org, a, n, now)})
                count += 1
        return count

    def list_alerts(self, org_id: str, limit: int = 50) -> list[dict]:
        items = self.t.query(f"ORG#{org_id}", "ALERT#")
        items.sort(key=lambda a: a["created_at"], reverse=True)
        return [{k: v for k, v in a.items() if k not in ("pk", "sk")} for a in items[:limit]]

    def acknowledge(self, user: User, org: dict, alert_id: str, now: datetime) -> dict:
        a = self.t.get(f"ORG#{org['org_id']}", f"ALERT#{alert_id}")
        if not a:
            raise HTTPException(404, "Alert not found")
        if not a.get("acknowledged"):
            a["acknowledged"] = {"by": user.name, "at": now_iso(now), "method": "in-app acknowledgement"}
            self.t.put(a)
            self.campus.history(org["org_id"], user, "alert_acknowledged", now, {"alert_id": alert_id})
        return {k: v for k, v in a.items() if k not in ("pk", "sk")}

    def send_test(self, user: User, org: dict, now: datetime) -> dict:
        test_id = "test-" + uuid.uuid4().hex[:10]
        alert = {
            "pk": f"ORG#{org['org_id']}", "sk": f"ALERT#{test_id}", "type": "alert", "alert_id": test_id,
            "kind": "test_notification", "created_at": now_iso(now), "trigger": "manual_test", "is_demo": org.get("is_demo", False),
            "activity_name": None, "occurrence_id": None,
            "subject": f"AirWindow test notification for {org['name']}",
            "message": (f"This is a test message requested by {user.name} for {org['name']} at {now_iso(now)}.\n"
                        "It confirms that AirWindow can publish to your opted-in email subscription. "
                        "No air-quality warning is attached to this message."),
            "notification": {"status": "prepared", "attempts": 0, "message_id": None, "last_error": None, "published_at": None},
            "acknowledged": None,
        }
        self.t.put(alert, if_not_exists=True)
        status = self._notify(org, alert, {}, now, ignore_cooldown=True)
        self.campus.history(org["org_id"], user, "test_notification", now, {"alert_id": test_id, "status": status})
        return self.t.get(f"ORG#{org['org_id']}", f"ALERT#{test_id}")

    # ------------------------------------------------------------------ subscriptions
    def list_subscriptions(self, org_id: str, refresh: bool = False) -> list[dict]:
        subs = self.t.query(f"ORG#{org_id}", "SUB#")
        out = []
        for s in subs:
            if refresh and s.get("status") not in ("unavailable_local_mode",):
                try:
                    st = self.notifier.refresh(s.get("subscription_arn"))
                    if st != s.get("status"):
                        s = {**s, "status": st, "checked_at": now_iso(self.svc.now())}
                        self.t.put(s)
                except Exception as exc:  # noqa: BLE001
                    s = {**s, "check_error": exc.__class__.__name__}
            out.append({k: s.get(k) for k in ("sub_id", "email_masked", "status", "requested_at", "checked_at", "check_error")})
        return out

    def confirmed_subscriptions(self, org_id: str) -> list[dict]:
        return [s for s in self.list_subscriptions(org_id, refresh=True) if s["status"] == "confirmed"]

    def add_subscription(self, user: User, org: dict, email: str, now: datetime) -> dict:
        email = (email or "").strip()
        if not EMAIL_RE.match(email):
            raise HTTPException(400, "Enter a valid email address")
        subs = self.t.query(f"ORG#{org['org_id']}", "SUB#")
        if any(s.get("email", "").lower() == email.lower() for s in subs):
            raise HTTPException(400, "This address is already subscribed")
        if len(subs) >= 3:
            raise HTTPException(400, "Up to 3 email subscriptions per organisation in this MVP")
        r = self.notifier.subscribe(org["org_id"], email)
        sub_id = uuid.uuid4().hex[:10]
        item = {"pk": f"ORG#{org['org_id']}", "sk": f"SUB#{sub_id}", "type": "subscription", "sub_id": sub_id,
                "email": email, "email_masked": mask_email(email), "status": r["status"],
                "subscription_arn": r.get("subscription_arn"), "requested_at": now_iso(now), "checked_at": now_iso(now),
                "requested_by": user.name}
        self.t.put(item)
        self.campus.history(org["org_id"], user, "subscription_requested", now, {"email": mask_email(email), "status": r["status"]})
        return {k: item[k] for k in ("sub_id", "email_masked", "status", "requested_at", "checked_at")}

    def remove_subscription(self, user: User, org: dict, sub_id: str, now: datetime) -> None:
        s = self.t.get(f"ORG#{org['org_id']}", f"SUB#{sub_id}")
        if not s:
            raise HTTPException(404, "Subscription not found")
        self.notifier.unsubscribe(s.get("subscription_arn"))
        self.t.delete(s["pk"], s["sk"])
        self.campus.history(org["org_id"], user, "subscription_removed", now, {"email": s.get("email_masked")})
