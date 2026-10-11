"""Impact counters. Honest by construction:

* counts are of records, not outcomes (acceptance is not proof an activity changed);
* participant figures are coordinator estimates summed per completed activity
  occurrence ("participant-sessions"), so the same students can be counted in
  several sessions; we never present them as unique people;
* index comparisons are modelled PM2.5 pollution-time differences between the
  original and accepted plan (same location, source and forecast retrieval) —
  not measured exposure, health improvement or ambient pollution reduction;
* demo records (replay/synthetic data or flagged by the coordinator) are kept
  separate from genuine usage.
"""

from __future__ import annotations

from typing import Any

from .campus import ACCEPT_TYPES
from .store import Table

NOTIF_STATUSES = ["publish_accepted", "failed", "no_confirmed_subscribers", "suppressed_cooldown", "not_sent_local_mode", "prepared"]


def compute(table: Table, scope: str = "genuine") -> dict[str, Any]:
    orgs = table.query("ENTITY#ORG", "", index="gsi2")
    if scope == "genuine":
        orgs = [o for o in orgs if not o.get("is_demo")]
    elif scope == "demo":
        orgs = [o for o in orgs if o.get("is_demo")]
    c: dict[str, Any] = {
        "organisations": len(orgs), "activities_registered": 0, "occurrences_assessed": 0, "assessments_run": 0,
        "recommendations_proposed": 0, "accepted": 0, "declined_kept_original": 0, "completed": 0, "not_held": 0,
        "participant_sessions_completed": 0, "largest_completed_activity": 0,
        "alerts": 0, "alerts_acknowledged": 0, "notifications": {s: 0 for s in NOTIF_STATUSES},
        "test_notifications": {s: 0 for s in NOTIF_STATUSES},
        "reports_submitted": 0, "reports_reviewed": 0, "report_followup_actions": 0, "reports_resolution_reviewed": 0,
    }
    comparisons = []
    for org in orgs:
        for it in table.query(f"ORG#{org['org_id']}"):
            t = it.get("type")
            if t == "activity" and it.get("active", True):
                c["activities_registered"] += 1
            elif t == "occurrence":
                if it.get("latest_assessment"):
                    c["occurrences_assessed"] += 1
                    c["assessments_run"] += int(it.get("assessments", 0))
                if it.get("ever_proposed"):
                    c["recommendations_proposed"] += 1
                d = it.get("decision") or {}
                if d.get("type") in ACCEPT_TYPES:
                    c["accepted"] += 1
                elif d.get("type") == "keep_original":
                    c["declined_kept_original"] += 1
                o = (it.get("outcome") or {}).get("outcome")
                if o in ("held_as_planned", "held_as_changed"):
                    c["completed"] += 1
                    p = int(it.get("participants") or 0)
                    c["participant_sessions_completed"] += p
                    c["largest_completed_activity"] = max(c["largest_completed_activity"], p)
                elif o == "not_held":
                    c["not_held"] += 1
                cmp_ = (d.get("details") or {}).get("comparison")
                if d.get("type") in ("accept_alternative", "shorten") and cmp_:
                    comparisons.append({
                        "org": org["name"], "activity": it.get("activity_name"), "date": it.get("date"), "type": d["type"],
                        "original": (d["details"].get("planned") or {}).get("label"),
                        "new": (d["details"].get("accepted") or {}).get("label") or f"shortened to {d['details'].get('shortened_to_min')} min",
                        "baseline_index": cmp_.get("baseline_index"), "new_index": cmp_.get("new_index"),
                        "pct_change": cmp_.get("pct_change"), "duration_changed": d["type"] == "shorten",
                        "forecast_retrieved_at": d["details"].get("forecast_retrieved_at"), "data_mode": d["details"].get("data_mode"),
                        "completed": o in ("held_as_planned", "held_as_changed"),
                    })
            elif t == "alert":
                st = (it.get("notification") or {}).get("status", "prepared")
                if it.get("kind") == "test_notification":
                    c["test_notifications"][st] = c["test_notifications"].get(st, 0) + 1
                    continue
                c["alerts"] += 1
                c["notifications"][st] = c["notifications"].get(st, 0) + 1
                if it.get("acknowledged"):
                    c["alerts_acknowledged"] += 1
            elif t == "report":
                c["reports_submitted"] += 1
                if it.get("status") != "submitted":
                    c["reports_reviewed"] += 1
                c["report_followup_actions"] += len(it.get("actions") or [])
                if it.get("status") == "resolution_reviewed":
                    c["reports_resolution_reviewed"] += 1
    valid = [x for x in comparisons if x["pct_change"] is not None and x["baseline_index"]]
    agg = None
    if valid:
        b = sum(x["baseline_index"] for x in valid)
        n = sum(x["new_index"] for x in valid)
        agg = {"count": len(valid), "baseline_index_sum": round(b, 1), "new_index_sum": round(n, 1),
               "pct_change": round((n - b) / b * 100, 1) if b > 0 else None}
    return {
        "scope": scope, "counters": c, "comparisons": comparisons, "comparison_total": agg,
        "labels": {
            "participants": "Coordinator estimates, summed per completed activity occurrence (participant-sessions). "
                            "The same students may appear in several sessions; this is not a count of unique people.",
            "comparisons": "Modelled PM2.5 pollution-time index of the accepted plan vs the original plan, from the same "
                           "location, source and forecast retrieval. Not measured exposure, not a health outcome, and not a "
                           "reduction in ambient pollution. Shortened activities change both time and concentration.",
            "notifications": "'publish_accepted' means SNS accepted the message; it does not prove delivery or reading. "
                             "Acknowledgements are recorded only when a coordinator acknowledges in the app.",
            "accepted": "Acceptance records a coordinator decision; it is not proof the change happened. Completion is recorded separately.",
            "indoor": "No indoor-exposure improvement is estimated: AirWindow has no indoor measurements.",
        },
    }
