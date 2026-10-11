"""School/college action workflow: organisations, activities, action cards,
coordinator decisions and an append-only audit history.

Privacy: only aggregate participant counts are stored (coordinator estimates).
No student names or medical information are collected.

Ownership: every organisation-scoped call goes through ``org_for`` which
returns 404 unless the signed-in user owns the organisation (or, for
member-level calls, has joined it). Authentication alone is never enough.
"""

from __future__ import annotations

import re
import secrets
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import HTTPException

from . import guidance, planner
from .aqi import classify_us_aqi
from .auth import User
from .providers import openmeteo as om
from .store import ConditionFailed, Table

KINDS = {"recess", "pe", "sports", "assembly", "event", "other"}
DECISIONS = {"accept_alternative", "shorten", "postpone", "cancel", "indoor_review", "keep_original"}
ACCEPT_TYPES = {"accept_alternative", "shorten", "postpone", "cancel", "indoor_review"}
OUTCOMES = {"held_as_planned", "held_as_changed", "not_held"}
HM_RE = re.compile(r"^([01]\d|2[0-4]):([0-5]\d)$")
AQI_STANDARD = "US AQI (calculated by Open-Meteo from CAMS Global modelled concentrations)"


def now_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def hm_to_min(v: str) -> int:
    m = HM_RE.match(v or "")
    if not m or (m.group(1) == "24" and m.group(2) != "00"):
        raise HTTPException(400, f"Invalid time {v!r}; use HH:MM")
    mins = int(m.group(1)) * 60 + int(m.group(2))
    if mins % 15:
        raise HTTPException(400, "Times must be on a 15-minute grid")
    return mins


def min_to_hm(m: int) -> str:
    return f"{m // 60:02d}:{m % 60:02d}"


def _clean_text(v: Any, max_len: int, field: str, min_len: int = 0) -> str:
    s = " ".join(str(v or "").split())
    if len(s) < min_len:
        raise HTTPException(400, f"{field} is too short")
    return s[:max_len]


class Campus:
    def __init__(self, table: Table, service, demo_mode: bool):
        self.t = table
        self.svc = service
        self.demo_mode = demo_mode  # replay data => every record is a demo record

    # ------------------------------------------------------------------ orgs
    def _org_item(self, org_id: str) -> dict | None:
        return self.t.get(f"ORG#{org_id}", "META")

    def org_for(self, user: User, org_id: str, role: str = "owner") -> dict:
        org = self._org_item(org_id)
        if not org:
            raise HTTPException(404, "Organisation not found")
        if org["owner_sub"] == user.sub:
            return org
        if role == "member" and self.t.get(f"USER#{user.sub}", f"MEMBER#{org_id}"):
            return org
        # Same response as a missing org: do not reveal other organisations.
        raise HTTPException(404, "Organisation not found")

    def list_orgs(self, user: User) -> list[dict]:
        owned = self.t.query(f"OWNER#{user.sub}", "ORG#", index="gsi1")
        out = [{**self.public_org(o), "role": "owner"} for o in owned]
        for m in self.t.query(f"USER#{user.sub}", "MEMBER#"):
            org = self._org_item(m["org_id"])
            if org:
                out.append({**self.public_org(org, member=True), "role": "member"})
        return out

    def public_org(self, org: dict, member: bool = False) -> dict:
        keys = ["org_id", "name", "lat", "lon", "location_label", "timezone", "threshold_aqi", "is_demo", "created_at"]
        d = {k: org.get(k) for k in keys}
        if not member:
            d["join_code"] = org.get("join_code")
            d["owner_name"] = org.get("owner_name")
        return d

    def create_org(self, user: User, body: dict, tz: str, now: datetime) -> dict:
        name = _clean_text(body.get("name"), 80, "Organisation name", 2)
        lat, lon = float(body["lat"]), float(body["lon"])
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise HTTPException(400, "Invalid campus location")
        try:
            ZoneInfo(tz)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(400, "Invalid timezone") from exc
        threshold = int(body.get("threshold_aqi", 100))
        if not 0 <= threshold <= 500:
            raise HTTPException(400, "Threshold must be 0-500 (US AQI)")
        if len(self.t.query(f"OWNER#{user.sub}", "ORG#", index="gsi1")) >= 5:
            raise HTTPException(400, "Limit of 5 organisations per coordinator in this MVP")
        org_id = uuid.uuid4().hex[:12]
        code = secrets.token_hex(4).upper()
        org = {
            "pk": f"ORG#{org_id}", "sk": "META", "type": "org", "version": 1,
            "gsi1pk": f"OWNER#{user.sub}", "gsi1sk": f"ORG#{org_id}",
            "gsi2pk": "ENTITY#ORG", "gsi2sk": f"{now_iso(now)}#{org_id}",
            "org_id": org_id, "name": name, "lat": round(lat, 5), "lon": round(lon, 5),
            "location_label": _clean_text(body.get("location_label"), 120, "Location label"),
            "timezone": tz, "threshold_aqi": threshold,
            "owner_sub": user.sub, "owner_name": user.name,
            # Records created while serving replay/synthetic data are always demo records.
            "is_demo": bool(body.get("is_demo")) or self.demo_mode,
            "data_mode_at_creation": self.svc.mode,
            "join_code": code, "created_at": now_iso(now),
        }
        self.t.put(org, if_not_exists=True)
        self.t.put({"pk": f"JOIN#{code}", "sk": "META", "type": "join", "org_id": org_id})
        self.history(org_id, user, "org_registered", now, {"name": name, "timezone": tz, "threshold_aqi": threshold, "is_demo": org["is_demo"]})
        return self.public_org(org)

    def update_org(self, user: User, org_id: str, body: dict, now: datetime) -> dict:
        org = self.org_for(user, org_id)
        changes = {}
        if "threshold_aqi" in body:
            th = int(body["threshold_aqi"])
            if not 0 <= th <= 500:
                raise HTTPException(400, "Threshold must be 0-500 (US AQI)")
            changes["threshold_aqi"] = th
        if "name" in body:
            changes["name"] = _clean_text(body["name"], 80, "Organisation name", 2)
        if not changes:
            return self.public_org(org)
        new = {**org, **changes, "version": org.get("version", 1) + 1}
        self.t.put(new, expect_version=org.get("version", 1))
        self.history(org_id, user, "org_updated", now, changes)
        return self.public_org(new)

    def join(self, user: User, code: str, now: datetime) -> dict:
        j = self.t.get(f"JOIN#{code.strip().upper()}", "META")
        if not j:
            raise HTTPException(404, "Join code not recognised")
        org = self._org_item(j["org_id"])
        if not org:
            raise HTTPException(404, "Join code not recognised")
        if org["owner_sub"] != user.sub:
            self.t.put({"pk": f"USER#{user.sub}", "sk": f"MEMBER#{org['org_id']}", "type": "membership",
                        "org_id": org["org_id"], "joined_at": now_iso(now), "name": user.name})
            self.history(org["org_id"], user, "member_joined", now, {})
        return self.public_org(org, member=True)

    # ------------------------------------------------------------------ activities
    def list_activities(self, org_id: str) -> list[dict]:
        return [a for a in self.t.query(f"ORG#{org_id}", "ACT#") if a.get("active", True)]

    def save_activity(self, user: User, org_id: str, body: dict, now: datetime, activity_id: str | None = None) -> dict:
        self.org_for(user, org_id)
        name = _clean_text(body.get("name"), 60, "Activity name", 2)
        kind = body.get("kind", "other")
        if kind not in KINDS:
            raise HTTPException(400, "Unknown activity kind")
        days = sorted({int(d) for d in body.get("days", [])})
        if not days or any(d < 0 or d > 6 for d in days):
            raise HTTPException(400, "Choose at least one weekday (0=Mon … 6=Sun)")
        start = hm_to_min(body.get("start", ""))
        duration = int(body.get("duration_min", 60))
        if not 15 <= duration <= 240 or duration % 15:
            raise HTTPException(400, "Duration must be 15–240 minutes in 15-minute steps")
        if start + duration > 1440:
            raise HTTPException(400, "Activity must finish by midnight")
        participants = int(body.get("participants", 0))
        if not 0 <= participants <= 5000:
            raise HTTPException(400, "Participant estimate must be 0–5000")
        alts = []
        for r in body.get("alternatives", [])[:4]:
            a, b = hm_to_min(r.get("start", "")), hm_to_min(r.get("end", ""))
            if b <= a:
                raise HTTPException(400, "Each alternative window must end after it starts")
            alts.append({"start": min_to_hm(a), "end": min_to_hm(b)})
        activity_id = activity_id or uuid.uuid4().hex[:10]
        item = {
            "pk": f"ORG#{org_id}", "sk": f"ACT#{activity_id}", "type": "activity",
            "activity_id": activity_id, "name": name, "kind": kind, "days": days,
            "start": min_to_hm(start), "duration_min": duration, "participants": participants,
            "participants_note": "coordinator estimate (aggregate count only)",
            "alternatives": alts, "location_note": _clean_text(body.get("location_note"), 60, "Location"),
            "active": True, "updated_at": now_iso(now),
        }
        self.t.put(item)
        self.history(org_id, user, "activity_saved", now, {"activity_id": activity_id, "name": name, "start": item["start"],
                                                           "duration_min": duration, "participants": participants})
        return item

    def remove_activity(self, user: User, org_id: str, activity_id: str, now: datetime) -> None:
        self.org_for(user, org_id)
        act = self.t.get(f"ORG#{org_id}", f"ACT#{activity_id}")
        if not act:
            raise HTTPException(404, "Activity not found")
        self.t.put({**act, "active": False, "updated_at": now_iso(now)})
        self.history(org_id, user, "activity_removed", now, {"activity_id": activity_id, "name": act["name"]})

    # ------------------------------------------------------------------ occurrences + cards
    def occurrences(self, org: dict, activities: list[dict], now: datetime, horizon_h: int = 48) -> list[dict]:
        tz = ZoneInfo(org["timezone"])
        today = now.astimezone(tz).date()
        out = []
        for offset in range(0, 3):
            d = today + timedelta(days=offset)
            for a in activities:
                if d.weekday() not in a["days"]:
                    continue
                start = planner.local_minutes_to_utc(d, hm_to_min(a["start"]), tz)
                end = start + timedelta(minutes=a["duration_min"])
                if start > now + timedelta(hours=horizon_h):
                    continue
                out.append({"occurrence_id": f"{d.isoformat()}_{a['activity_id']}", "date": d.isoformat(),
                            "activity": a, "start": start, "end": end})
        out.sort(key=lambda o: o["start"])
        return out

    def occurrence_item(self, org_id: str, occ_id: str) -> dict | None:
        d, aid = occ_id.split("_", 1)
        return self.t.get(f"ORG#{org_id}", f"OCC#{d}#{aid}")

    def build_card(self, org: dict, occ: dict, series: dict, aq_meta: dict, now: datetime, mode_info: dict) -> dict:
        a = occ["activity"]
        tz = ZoneInfo(org["timezone"])
        start_min = hm_to_min(a["start"])
        ranges = [(start_min, start_min + a["duration_min"])]
        ranges += [(hm_to_min(r["start"]), hm_to_min(r["end"])) for r in a.get("alternatives", [])]
        p = planner.PlanInput(
            timezone=org["timezone"], day=date.fromisoformat(occ["date"]),
            allowed_start_min=ranges[0][0], allowed_end_min=ranges[0][1],
            duration_min=a["duration_min"], baseline_start_min=start_min,
            threshold_aqi=int(org["threshold_aqi"]), allowed_ranges=tuple(ranges),
        )
        res = planner.plan(p, series, now)
        planned = res["baseline"]
        exceeds = (not planned["meets_threshold"]) if planned["complete"] else None
        best = res["best"]
        alternative = None
        if best and planned["complete"] and best["start_utc"] != planned["start_utc"] and best["pm25_index"] < planned["pm25_index"]:
            alternative = best
        least = None
        if exceeds and not best:
            least = res["least_polluted_available"]
        in_past = planned["starts_in_past"]
        if not planned["complete"]:
            status = "data_unavailable"
        elif exceeds and alternative:
            status = "exceeds_with_alternative"
        elif exceeds:
            status = "exceeds_no_alternative"
        else:
            status = "within_threshold"

        chosen = alternative or least
        comparison = None
        if chosen and planned["complete"] and planned["pm25_index"] and planned["pm25_index"] > 0:
            comparison = {
                "pct_change": round((chosen["pm25_index"] - planned["pm25_index"]) / planned["pm25_index"] * 100, 1),
                "abs_change": round(chosen["pm25_index"] - planned["pm25_index"], 2),
                "basis": "same location, duration, source and forecast retrieval",
            }

        shorten = []
        if planned["complete"] and not in_past:
            s0 = datetime.fromisoformat(planned["start_utc"].replace("Z", "+00:00"))
            for d in sorted({max(15, (a["duration_min"] // 2) // 15 * 15), max(15, a["duration_min"] - 15)}):
                if d >= a["duration_min"]:
                    continue
                w = planner.evaluate_window(s0, s0 + timedelta(minutes=d), series, int(org["threshold_aqi"]))
                if w.complete and planned["pm25_index"]:
                    shorten.append({"duration_min": d, "pm25_index": round(w.pm25_index, 2), "peak_aqi": w.peak_aqi,
                                    "pct_change": round((w.pm25_index - planned["pm25_index"]) / planned["pm25_index"] * 100, 1),
                                    "note": "Change reflects both the shorter time outdoors and the forecast concentration."})

        cat = classify_us_aqi(planned["peak_aqi"]) if planned["complete"] else classify_us_aqi(None)
        expl = self._explain(org, planned, status, alternative, least, comparison)
        item = self.occurrence_item(org["org_id"], occ["occurrence_id"]) or {}
        return {
            "occurrence_id": occ["occurrence_id"], "date": occ["date"],
            "activity": {k: a[k] for k in ("activity_id", "name", "kind", "start", "duration_min", "participants", "location_note", "alternatives")},
            "org": {"org_id": org["org_id"], "name": org["name"], "timezone": org["timezone"], "location_label": org.get("location_label"),
                    "lat": org["lat"], "lon": org["lon"]},
            "planned": planned, "status": status, "exceeds": exceeds, "in_past": in_past,
            "threshold_aqi": int(org["threshold_aqi"]), "aqi_standard": AQI_STANDARD,
            "planned_category": cat.as_dict(),
            "alternative": alternative, "least_polluted": least, "comparison": comparison,
            "shorten_options": shorten,
            "candidates": [w for w in res["windows"] if w["complete"] and not w["starts_in_past"]],
            "allowed_ranges": res["allowed_ranges"],
            "guidance": guidance.for_category(cat.key),
            "indoor_note": guidance.INDOOR_NOTE,
            "provenance": {
                "source": om.AQ_SOURCE["provider"], "model": om.AQ_SOURCE["model"], "data_type": "model_forecast",
                "valid_from_utc": planned["start_utc"], "valid_to_utc": planned["end_utc"],
                "retrieved_at": aq_meta.get("retrieved_at"), "cache_status": aq_meta.get("status"), "stale": bool(aq_meta.get("stale")),
                "spatial_resolution": om.AQ_SOURCE["spatial_resolution"], "native_time_step": om.AQ_SOURCE["native_time_step"],
                **mode_info,
            },
            "explanation": expl,
            "planner_explanations": res["explanations"],
            "decision": item.get("decision"), "outcome": item.get("outcome"),
            "last_alert": item.get("last_alert"),
        }

    @staticmethod
    def _explain(org, planned, status, alternative, least, comparison) -> list[str]:
        if status == "data_unavailable":
            return ["Forecast data is missing for part of the planned time, so it cannot be assessed. No value is assumed."]
        lines = []
        cat = classify_us_aqi(planned["peak_aqi"])
        verb = "exceeds" if status.startswith("exceeds") else "is within"
        lines.append(
            f"Planned {planned['label']}: peak forecast US AQI {planned['peak_aqi']} ({cat.label}) {verb} your planning "
            f"threshold of {org['threshold_aqi']}; PM2.5 pollution-time index {planned['pm25_index']:.1f} µg·h/m³."
        )
        if alternative:
            pct = f" ({comparison['pct_change']:+.1f}% index)" if comparison else ""
            lines.append(f"Lowest-index eligible time within your permitted windows: {alternative['label']}, peak AQI "
                         f"{alternative['peak_aqi']}, index {alternative['pm25_index']:.1f}{pct}.")
        elif least:
            pct = f" ({comparison['pct_change']:+.1f}% index)" if comparison else ""
            lines.append(f"No permitted time meets the threshold. Least-polluted permitted time: {least['label']} "
                         f"(peak AQI {least['peak_aqi']}){pct} — it still exceeds the threshold and is not a safe window.")
        lines.append("Index = Σ hourly forecast PM2.5 × hours of overlap: a comparative planning number, not dose or health risk.")
        return lines

    # ------------------------------------------------------------------ occurrence state
    def save_assessment(self, org_id: str, card: dict, trigger: str, now: datetime, extra: dict | None = None) -> dict:
        """Upsert the occurrence's latest assessment with optimistic concurrency."""
        d, aid = card["occurrence_id"].split("_", 1)
        for _ in range(4):
            cur = self.t.get(f"ORG#{org_id}", f"OCC#{d}#{aid}")
            base = cur or {"pk": f"ORG#{org_id}", "sk": f"OCC#{d}#{aid}", "type": "occurrence", "version": 0,
                           "occurrence_id": card["occurrence_id"], "date": d, "activity_id": aid, "assessments": 0}
            new = {
                **base, **(extra or {}),
                "version": base.get("version", 0) + 1,
                "activity_name": card["activity"]["name"],
                "participants": card["activity"]["participants"],
                "planned_start_utc": card["planned"]["start_utc"], "planned_end_utc": card["planned"]["end_utc"],
                "assessments": base.get("assessments", 0) + 1,
                "latest_assessment": {
                    "at": now_iso(now), "trigger": trigger, "status": card["status"], "exceeds": card["exceeds"],
                    "planned_peak_aqi": card["planned"]["peak_aqi"], "planned_index": card["planned"]["pm25_index"],
                    "alternative_start_utc": (card["alternative"] or {}).get("start_utc"),
                    "retrieved_at": card["provenance"]["retrieved_at"], "data_mode": card["provenance"]["mode"],
                },
                "ever_proposed": bool(base.get("ever_proposed")) or card["status"] in ("exceeds_with_alternative", "exceeds_no_alternative")
                or bool(card["alternative"]),
            }
            try:
                if cur:
                    self.t.put(new, expect_version=cur.get("version", 0))
                else:
                    self.t.put(new, if_not_exists=True)
                return new
            except ConditionFailed:
                continue
        raise HTTPException(409, "Concurrent update; please retry")

    def _update_occurrence(self, org_id: str, occ_id: str, mutate) -> dict:
        d, aid = occ_id.split("_", 1)
        for _ in range(4):
            cur = self.t.get(f"ORG#{org_id}", f"OCC#{d}#{aid}")
            if not cur:
                raise HTTPException(404, "Assess the activity before recording an action")
            new = mutate(dict(cur))
            new["version"] = cur.get("version", 0) + 1
            try:
                self.t.put(new, expect_version=cur.get("version", 0))
                return new
            except ConditionFailed:
                continue
        raise HTTPException(409, "Concurrent update; please retry")

    # ------------------------------------------------------------------ coordinator actions
    def apply_action(self, user: User, org: dict, card: dict, body: dict, now: datetime) -> dict:
        kind = body.get("type")
        note = _clean_text(body.get("note"), 300, "Note")
        details: dict[str, Any] = {"planned": _slim(card["planned"]), "threshold_aqi": card["threshold_aqi"],
                                   "forecast_retrieved_at": card["provenance"]["retrieved_at"], "data_mode": card["provenance"]["mode"]}
        if kind == "complete":
            outcome = body.get("outcome")
            if outcome not in OUTCOMES:
                raise HTTPException(400, "Outcome must be held_as_planned, held_as_changed or not_held")
            if not card["in_past"]:
                raise HTTPException(400, "An outcome can only be recorded once the planned time has started")
            rec = {"outcome": outcome, "at": now_iso(now), "by": user.name, "note": note}
            occ = self._update_occurrence(org["org_id"], card["occurrence_id"], lambda o: {**o, "outcome": rec})
            self.history(org["org_id"], user, "outcome_recorded", now, {"occurrence_id": card["occurrence_id"], **rec})
            return occ
        if kind not in DECISIONS:
            raise HTTPException(400, "Unknown action type")
        if card["in_past"] and kind in ("accept_alternative", "shorten"):
            raise HTTPException(400, "The planned time has already started")

        if kind == "accept_alternative":
            start = body.get("start_utc")
            chosen = next((w for w in card["candidates"] if w["start_utc"] == start), None)
            if not chosen:
                raise HTTPException(400, "Choose one of the complete permitted windows shown on the card")
            details["accepted"] = _slim(chosen)
            details["accepted_exceeds_threshold"] = not chosen["meets_threshold"]
            details["comparison"] = _compare(card["planned"], chosen, same_duration=True)
        elif kind == "shorten":
            d = int(body.get("duration_min", 0))
            opt = next((o for o in card["shorten_options"] if o["duration_min"] == d), None)
            if not opt:
                raise HTTPException(400, "Choose one of the shortened durations shown on the card")
            details["shortened_to_min"] = d
            details["comparison"] = {"pct_change": opt["pct_change"], "baseline_index": card["planned"]["pm25_index"],
                                     "new_index": opt["pm25_index"], "basis": "same start, location, source and forecast retrieval",
                                     "note": opt["note"]}
        elif kind == "keep_original":
            reason = _clean_text(body.get("reason"), 300, "Reason", 5)
            details["reason"] = reason
        elif kind == "indoor_review":
            details["indoor_air_quality"] = "unverified — no indoor measurements available"
            details["indoor_note"] = guidance.INDOOR_NOTE
        details["note"] = note
        rec = {"type": kind, "at": now_iso(now), "by": user.name, "details": details}
        occ = self._update_occurrence(org["org_id"], card["occurrence_id"], lambda o: {**o, "decision": rec})
        self.history(org["org_id"], user, f"decision_{kind}", now, {"occurrence_id": card["occurrence_id"], **details})
        return occ

    # ------------------------------------------------------------------ history
    def history(self, org_id: str, user: User | None, event: str, now: datetime, details: dict) -> None:
        self.t.put({
            "pk": f"ORG#{org_id}", "sk": f"HIST#{now_iso(now)}#{uuid.uuid4().hex[:6]}", "type": "history",
            "event": event, "actor": user.name if user else "system (scheduled assessment)",
            "actor_sub": user.sub if user else None, "at": now_iso(now), "details": details,
            "data_mode": self.svc.mode,
        })

    def list_history(self, org_id: str, limit: int = 100) -> list[dict]:
        return [{k: v for k, v in h.items() if k not in ("pk", "actor_sub")}
                for h in self.t.query(f"ORG#{org_id}", "HIST#", reverse=True, limit=limit)]


def _slim(w: dict) -> dict:
    return {k: w.get(k) for k in ("start_utc", "end_utc", "label", "pm25_index", "peak_aqi", "meets_threshold")}


def _compare(base: dict, other: dict, same_duration: bool) -> dict:
    if not base.get("pm25_index") or base["pm25_index"] <= 0 or other.get("pm25_index") is None:
        return {"pct_change": None, "reason": "Baseline index missing or not positive"}
    return {
        "pct_change": round((other["pm25_index"] - base["pm25_index"]) / base["pm25_index"] * 100, 1),
        "baseline_index": base["pm25_index"], "new_index": other["pm25_index"],
        "basis": "same location, duration, source and forecast retrieval" if same_duration else "same location, source and forecast retrieval",
    }
