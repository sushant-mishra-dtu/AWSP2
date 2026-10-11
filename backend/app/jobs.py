"""Scheduled assessment (EventBridge Scheduler -> this Lambda handler).

Uses exactly the same ``Alerts.assess_org`` path as the in-app
"Check upcoming activities now" button. Safe to invoke repeatedly: alert
creation is de-duplicated with conditional writes.

Local use (labelled as a manual invocation of the scheduled path):
    python -m app.jobs
"""

from __future__ import annotations

import asyncio
import json
import logging

from .runtime import build

log = logging.getLogger("airwindow.jobs")
logging.basicConfig(level=logging.INFO)

_rt = None


def _runtime():
    global _rt
    if _rt is None:
        _rt = build()
    return _rt


def handler(event, context):
    rt = _runtime()
    source = (event or {}).get("source") or "scheduler"
    result = asyncio.run(rt.alerts.assess_all(trigger="schedule"))
    result["invocation"] = {"source": source, "request_id": getattr(context, "aws_request_id", None)}
    log.info(json.dumps({"evt": "scheduled_assessment", **{k: result[k] for k in ("trigger", "orgs")},
                         "alerts_created": sum(r.get("alerts_created", 0) for r in result["results"]),
                         "duplicates_skipped": sum(r.get("duplicates_skipped", 0) for r in result["results"])}))
    return result


if __name__ == "__main__":
    print(json.dumps(handler({"source": "local-cli"}, None), indent=2, default=str))
