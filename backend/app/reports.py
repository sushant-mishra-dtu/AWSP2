"""Community action tracker for a campus.

Reports are UNVERIFIED observations. A coordinator (organisation owner) is the
authorised reviewer. Workflow:
  submitted -> reviewed -> assigned -> action_recorded -> resolution_reviewed
Nothing here contacts authorities or publishes reports, and nothing infers that
a reported activity caused any measured or forecast AQI. A resolved task is
not evidence that emissions fell.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import HTTPException

from .auth import User
from .campus import Campus, _clean_text, now_iso
from .evidence import ALLOWED_TYPES, EvidenceError
from .store import Table

CATEGORIES = {
    "open_burning": "Visible open waste burning",
    "construction_dust": "Construction dust",
    "vehicle_idling": "Vehicle idling near the campus gate",
    "other": "Other visible pollution concern",
}
REVIEW_OUTCOMES = {
    "plausible_follow_up": "Plausible — follow up on campus",
    "insufficient_information": "Insufficient information",
    "not_actionable": "Not actionable by the campus",
}
TASKS = {
    "investigate_burning": "Ask campus staff to investigate the reported burning",
    "check_dust_control": "Check dust-control practices at the construction site",
    "no_idling_reminder": "Place a no-idling reminder at the campus gate",
    "follow_up_inspection": "Record a follow-up inspection",
    "other": "Other campus task",
}
FLOW = ["submitted", "reviewed", "assigned", "action_recorded", "resolution_reviewed"]
DISCLAIMER = ("Unverified community report. A report or photo is not verified evidence of a pollutant source, and it is not "
              "linked to any measured or forecast AQI. AirWindow never contacts authorities or publishes reports.")


class Reports:
    def __init__(self, table: Table, campus: Campus, evidence):
        self.t = table
        self.campus = campus
        self.ev = evidence

    def _get(self, org_id: str, report_id: str) -> dict:
        r = self.t.get(f"ORG#{org_id}", f"REPORT#{report_id}")
        if not r:
            raise HTTPException(404, "Report not found")
        return r

    def _view(self, r: dict, can_moderate: bool) -> dict:
        d = {k: v for k, v in r.items() if k not in ("pk", "sk", "submitted_by_sub")}
        d["verification"] = "reviewed by campus coordinator (not independent verification)" if r["status"] != "submitted" else "unverified"
        d["disclaimer"] = DISCLAIMER
        d["can_moderate"] = can_moderate
        return d

    def create(self, user: User, org: dict, body: dict, now: datetime) -> dict:
        cat = body.get("category")
        if cat not in CATEGORIES:
            raise HTTPException(400, "Unknown report category")
        lat, lon = float(body["lat"]), float(body["lon"])
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise HTTPException(400, "Invalid location")
        observed = str(body.get("observed_at") or "")
        try:
            obs_dt = datetime.fromisoformat(observed.replace("Z", "+00:00"))
            if obs_dt.tzinfo is None:
                raise ValueError
        except ValueError as exc:
            raise HTTPException(400, "observed_at must be an ISO time with timezone") from exc
        if (obs_dt - now).total_seconds() > 600:  # allow small clock skew
            raise HTTPException(400, "Observation time cannot be in the future")
        rid = uuid.uuid4().hex[:12]
        item = {
            "pk": f"ORG#{org['org_id']}", "sk": f"REPORT#{rid}", "type": "report", "report_id": rid,
            "category": cat, "category_label": CATEGORIES[cat], "lat": round(lat, 5), "lon": round(lon, 5),
            "observed_at": obs_dt.isoformat(), "description": _clean_text(body.get("description"), 500, "Description", 5),
            "photo": None, "status": "submitted", "submitted_by": user.name, "submitted_by_sub": user.sub,
            "submitted_at": now_iso(now), "review": None, "assignment": None, "actions": [], "resolution": None,
            "history": [{"status": "submitted", "by": user.name, "at": now_iso(now)}],
            "is_demo": org.get("is_demo", False),
        }
        self.t.put(item, if_not_exists=True)
        self.campus.history(org["org_id"], user, "report_submitted", now, {"report_id": rid, "category": cat})
        return self._view(item, org["owner_sub"] == user.sub)

    def list(self, user: User, org: dict) -> list[dict]:
        owner = org["owner_sub"] == user.sub
        items = self.t.query(f"ORG#{org['org_id']}", "REPORT#")
        if not owner:
            items = [r for r in items if r.get("submitted_by_sub") == user.sub]
        items.sort(key=lambda r: r["submitted_at"], reverse=True)
        return [self._view(r, owner) for r in items]

    def transition(self, user: User, org: dict, report_id: str, body: dict, now: datetime) -> dict:
        if org["owner_sub"] != user.sub:
            raise HTTPException(403, "Only the campus coordinator can review reports")
        r = self._get(org["org_id"], report_id)
        step = body.get("step")
        note = _clean_text(body.get("note"), 400, "Note")
        cur = FLOW.index(r["status"])
        if step == "review":
            if r["status"] != "submitted":
                raise HTTPException(400, "Report already reviewed")
            outcome = body.get("outcome")
            if outcome not in REVIEW_OUTCOMES:
                raise HTTPException(400, "Choose a review outcome")
            r["review"] = {"outcome": outcome, "label": REVIEW_OUTCOMES[outcome], "by": user.name, "at": now_iso(now), "note": note}
            r["status"] = "reviewed"
        elif step == "assign":
            if cur < FLOW.index("reviewed") or r["status"] == "resolution_reviewed":
                raise HTTPException(400, "Review the report before assigning a task")
            task = body.get("task")
            if task not in TASKS:
                raise HTTPException(400, "Choose a campus task")
            r["assignment"] = {"task": task, "label": TASKS[task], "assignee": _clean_text(body.get("assignee"), 60, "Assignee", 2),
                               "by": user.name, "at": now_iso(now), "note": note}
            r["status"] = "assigned"
        elif step == "record_action":
            if cur < FLOW.index("assigned") or r["status"] == "resolution_reviewed":
                raise HTTPException(400, "Assign a task before recording an action")
            r["actions"] = [*r.get("actions", []), {"by": user.name, "at": now_iso(now), "note": _clean_text(body.get("note"), 400, "Action note", 5)}]
            r["status"] = "action_recorded"
        elif step == "review_resolution":
            if r["status"] != "action_recorded":
                raise HTTPException(400, "Record a follow-up action first")
            r["resolution"] = {"by": user.name, "at": now_iso(now), "note": note,
                               "caveat": "Resolution reviewed on campus; this does not show that emissions were reduced."}
            r["status"] = "resolution_reviewed"
        else:
            raise HTTPException(400, "Unknown step")
        r["history"] = [*r.get("history", []), {"status": r["status"], "by": user.name, "at": now_iso(now), "note": note}]
        self.t.put(r)
        self.campus.history(org["org_id"], user, f"report_{step}", now, {"report_id": report_id, "status": r["status"]})
        return self._view(r, True)

    # ------------------------------------------------------------------ photo evidence
    def photo_upload(self, user: User, org: dict, report_id: str, content_type: str, size: int) -> dict:
        r = self._get(org["org_id"], report_id)
        if r.get("submitted_by_sub") != user.sub and org["owner_sub"] != user.sub:
            raise HTTPException(404, "Report not found")
        if r.get("photo"):
            raise HTTPException(400, "This report already has a photo")
        key = f"reports/{org['org_id']}/{report_id}/{uuid.uuid4().hex[:8]}{ALLOWED_TYPES.get(content_type, '')}"
        try:
            target = self.ev.upload_target(key, content_type, int(size))
        except EvidenceError as exc:
            raise HTTPException(400, str(exc)) from exc
        r["pending_photo"] = {"key": key, "content_type": content_type}
        self.t.put(r)
        return target

    def photo_confirm(self, user: User, org: dict, report_id: str, now: datetime) -> dict:
        r = self._get(org["org_id"], report_id)
        if r.get("submitted_by_sub") != user.sub and org["owner_sub"] != user.sub:
            raise HTTPException(404, "Report not found")
        pending = r.get("pending_photo")
        if not pending:
            raise HTTPException(400, "No upload in progress")
        try:
            size = self.ev.verify(pending["key"], pending["content_type"])
        except EvidenceError as exc:
            r.pop("pending_photo", None)
            self.t.put(r)
            raise HTTPException(400, str(exc)) from exc
        r["photo"] = {**pending, "size": size, "uploaded_at": now_iso(now), "storage": self.ev.kind,
                      "note": "Private; visible only to the submitter and the campus coordinator. Not verified evidence."}
        r.pop("pending_photo", None)
        self.t.put(r)
        return self._view(r, org["owner_sub"] == user.sub)

    def photo_url(self, user: User, org: dict, report_id: str) -> dict[str, Any]:
        r = self._get(org["org_id"], report_id)
        if r.get("submitted_by_sub") != user.sub and org["owner_sub"] != user.sub:
            raise HTTPException(404, "Report not found")
        if not r.get("photo"):
            raise HTTPException(404, "No photo")
        return {"url": self.ev.view_url(r["photo"]["key"]), "expires_in_s": 120}
