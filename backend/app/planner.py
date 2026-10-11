"""Activity-window planner (pure, no I/O).

Given one hourly forecast series for one location (one source, one retrieval),
enumerate every candidate activity window inside the user's permitted local
hours and compute:

* PM2.5 pollution-time index = sum(PM2.5 concentration x overlap duration),
  in micrograms*hours per cubic metre (ug*h/m3). Partial hourly overlaps are
  weighted by the overlapping fraction of the hour.
* Peak forecast US AQI over every interval the window touches.

Windows touching an interval with missing PM2.5 or US AQI are incomplete and
are never ranked. Complete windows whose peak AQI is at or below the planning
threshold are "eligible" and are ranked by (index, peak AQI, earliest start).

This is a comparative planning index. It is not inhaled dose, exposure, or a
medical risk estimate, and moving an activity does not change ambient air.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from .aqi import classify_us_aqi, round_aqi

INDEX_UNITS = "µg·h/m³"


@dataclass(frozen=True)
class SeriesPoint:
    """One provider interval [start, start + interval)."""

    pm25: float | None
    us_aqi: float | None


@dataclass(frozen=True)
class PlanInput:
    timezone: str
    day: date
    allowed_start_min: int  # minutes after local midnight, inclusive
    allowed_end_min: int  # minutes after local midnight, exclusive end (<= 1440)
    duration_min: int
    baseline_start_min: int
    threshold_aqi: int
    step_min: int = 15
    interval_s: int = 3600


@dataclass
class Window:
    start: datetime
    end: datetime
    complete: bool
    missing_intervals: list[datetime] = field(default_factory=list)
    pm25_index: float | None = None
    peak_aqi: int | None = None
    meets_threshold: bool = False
    in_allowed_hours: bool = True
    starts_in_past: bool = False

    @property
    def eligible(self) -> bool:
        return (
            self.complete
            and self.meets_threshold
            and self.in_allowed_hours
            and not self.starts_in_past
        )

    def as_dict(self, tz: ZoneInfo) -> dict[str, Any]:
        cat = classify_us_aqi(self.peak_aqi)
        return {
            "start_utc": _iso_utc(self.start),
            "end_utc": _iso_utc(self.end),
            "start_local": self.start.astimezone(tz).isoformat(),
            "end_local": self.end.astimezone(tz).isoformat(),
            "label": window_label(self, tz),
            "complete": self.complete,
            "missing_intervals_utc": [_iso_utc(m) for m in self.missing_intervals],
            "pm25_index": None if self.pm25_index is None else round(self.pm25_index, 2),
            "pm25_index_units": INDEX_UNITS,
            "peak_aqi": self.peak_aqi,
            "peak_category": cat.as_dict(),
            "meets_threshold": self.meets_threshold,
            "in_allowed_hours": self.in_allowed_hours,
            "starts_in_past": self.starts_in_past,
            "eligible": self.eligible,
        }


class PlanInputError(ValueError):
    pass


def _iso_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def local_minutes_to_utc(day: date, minutes: int, tz: ZoneInfo) -> datetime:
    """Convert 'minutes after local midnight on `day`' (wall clock) to UTC.

    1440 means the following local midnight. Wall-clock arithmetic is used so
    that "07:00" means 07:00 on the clock even on a DST transition day.
    """
    if not 0 <= minutes <= 1440:
        raise PlanInputError("minutes must be between 0 and 1440")
    base = datetime.combine(day, time(0, 0)) + timedelta(minutes=minutes)
    return base.replace(tzinfo=tz).astimezone(timezone.utc)


def window_label(w: Window, tz: ZoneInfo) -> str:
    s = w.start.astimezone(tz)
    e = w.end.astimezone(tz)
    return f"{s:%H:%M}–{e:%H:%M}"


def _floor_to_interval(dt: datetime, interval_s: int) -> datetime:
    ts = dt.timestamp()
    return datetime.fromtimestamp(math.floor(ts / interval_s) * interval_s, timezone.utc)


def evaluate_window(
    start: datetime,
    end: datetime,
    series: dict[datetime, SeriesPoint],
    threshold_aqi: int,
    interval_s: int = 3600,
) -> Window:
    """Score one window. `series` keys are interval starts in UTC."""
    if end <= start:
        raise PlanInputError("window end must be after start")
    w = Window(start=start, end=end, complete=True)
    step = timedelta(seconds=interval_s)
    t = _floor_to_interval(start, interval_s)
    index = 0.0
    peak: int | None = None
    while t < end:
        t_end = t + step
        overlap_s = (min(end, t_end) - max(start, t)).total_seconds()
        if overlap_s > 0:
            p = series.get(t)
            aqi = round_aqi(p.us_aqi) if p else None
            pm = p.pm25 if p else None
            pm_ok = (
                pm is not None
                and not isinstance(pm, bool)
                and isinstance(pm, (int, float))
                and math.isfinite(pm)
                and pm >= 0
            )
            if not pm_ok or aqi is None:
                w.complete = False
                w.missing_intervals.append(t)
            else:
                index += float(pm) * (overlap_s / 3600.0)
                peak = aqi if peak is None else max(peak, aqi)
        t = t_end
    if w.complete:
        w.pm25_index = index
        w.peak_aqi = peak
        w.meets_threshold = peak is not None and peak <= threshold_aqi
    return w


def _rank_key(w: Window) -> tuple[float, int, float]:
    assert w.pm25_index is not None and w.peak_aqi is not None
    return (round(w.pm25_index, 6), w.peak_aqi, w.start.timestamp())


def validate(p: PlanInput) -> ZoneInfo:
    try:
        tz = ZoneInfo(p.timezone)
    except Exception as exc:  # noqa: BLE001 - zoneinfo raises several types
        raise PlanInputError(f"unknown timezone: {p.timezone}") from exc
    if not 0 <= p.allowed_start_min < p.allowed_end_min <= 1440:
        raise PlanInputError("allowed hours must satisfy 0 <= start < end <= 24:00")
    if not 15 <= p.duration_min <= 480 or p.duration_min % 15:
        raise PlanInputError("duration must be 15-480 minutes in 15-minute steps")
    if p.duration_min > p.allowed_end_min - p.allowed_start_min:
        raise PlanInputError("activity is longer than the permitted hours")
    if not 0 <= p.baseline_start_min <= 1440 - 15:
        raise PlanInputError("baseline start must be within the selected day")
    if not 0 <= p.threshold_aqi <= 500:
        raise PlanInputError("planning threshold must be between 0 and 500")
    if p.step_min <= 0 or 60 % p.step_min:
        raise PlanInputError("step must divide 60")
    if (p.baseline_start_min - p.allowed_start_min) % p.step_min or p.allowed_start_min % p.step_min:
        # Keeps the baseline on the candidate grid, so an eligible baseline is
        # always one of the ranked candidates and comparisons stay consistent.
        raise PlanInputError(f"times must be on a {p.step_min}-minute grid")
    return tz


def plan(
    p: PlanInput,
    series: dict[datetime, SeriesPoint],
    now: datetime,
) -> dict[str, Any]:
    tz = validate(p)
    duration = timedelta(minutes=p.duration_min)
    allowed_start = local_minutes_to_utc(p.day, p.allowed_start_min, tz)
    allowed_end = local_minutes_to_utc(p.day, p.allowed_end_min, tz)

    windows: list[Window] = []
    m = p.allowed_start_min
    while m + p.duration_min <= p.allowed_end_min:
        start = local_minutes_to_utc(p.day, m, tz)
        end = start + duration
        if end <= allowed_end:
            w = evaluate_window(start, end, series, p.threshold_aqi, p.interval_s)
            w.starts_in_past = start < now
            windows.append(w)
        m += p.step_min

    future = [w for w in windows if not w.starts_in_past]
    complete = [w for w in future if w.complete]
    eligible = sorted((w for w in complete if w.meets_threshold), key=_rank_key)
    best = eligible[0] if eligible else None
    least = None if best else (min(complete, key=_rank_key) if complete else None)

    b_start = local_minutes_to_utc(p.day, p.baseline_start_min, tz)
    baseline = evaluate_window(b_start, b_start + duration, series, p.threshold_aqi, p.interval_s)
    baseline.in_allowed_hours = allowed_start <= b_start and b_start + duration <= allowed_end
    baseline.starts_in_past = b_start < now

    if best:
        status = "ok"
    elif complete:
        status = "no_eligible_window"
    elif future:
        status = "no_complete_window"
    else:
        status = "no_future_window"

    chosen = best or least
    comparison = compare(baseline, chosen, is_eligible=best is not None)

    out = {
        "status": status,
        "timezone": p.timezone,
        "day": p.day.isoformat(),
        "threshold_aqi": p.threshold_aqi,
        "duration_min": p.duration_min,
        "step_min": p.step_min,
        "allowed": {
            "start_local": allowed_start.astimezone(tz).isoformat(),
            "end_local": allowed_end.astimezone(tz).isoformat(),
        },
        "now_utc": _iso_utc(now),
        "counts": {
            "candidates": len(windows),
            "in_past": len(windows) - len(future),
            "incomplete": len(future) - len(complete),
            "complete": len(complete),
            "eligible": len(eligible),
        },
        "best": best.as_dict(tz) if best else None,
        "least_polluted_available": least.as_dict(tz) if least else None,
        "alternatives": [w.as_dict(tz) for w in eligible[1:4]],
        "baseline": baseline.as_dict(tz),
        "comparison": comparison,
        "windows": [w.as_dict(tz) for w in windows],
        "index_units": INDEX_UNITS,
    }
    out["explanations"] = explain(out)
    return out


def compare(baseline: Window, chosen: Window | None, is_eligible: bool) -> dict[str, Any]:
    res: dict[str, Any] = {
        "available": False,
        "pct_change": None,
        "abs_change": None,
        "reason": None,
        "chosen_is_eligible": is_eligible,
        "same_window": False,
    }
    if chosen is None:
        res["reason"] = "No complete future window is available to compare."
        return res
    if not baseline.complete:
        res["reason"] = "Your planned slot has missing forecast intervals, so no comparison is made."
        return res
    assert baseline.pm25_index is not None and chosen.pm25_index is not None
    res["same_window"] = baseline.start == chosen.start and baseline.end == chosen.end
    res["abs_change"] = round(chosen.pm25_index - baseline.pm25_index, 2)
    if baseline.pm25_index <= 0:
        res["reason"] = "Your planned slot has a zero index, so a percentage change is undefined."
        return res
    res["available"] = True
    res["pct_change"] = round(
        (chosen.pm25_index - baseline.pm25_index) / baseline.pm25_index * 100.0, 1
    )
    return res


def _fmt_idx(v: float | None) -> str:
    return "n/a" if v is None else f"{v:.1f} {INDEX_UNITS}"


def explain(r: dict[str, Any]) -> list[str]:
    """Deterministic plain-language explanation built only from computed values."""
    lines: list[str] = []
    th = r["threshold_aqi"]
    b = r["baseline"]
    c = r["comparison"]

    if r["status"] == "ok":
        w = r["best"]
        lines.append(
            f"Lowest PM2.5 pollution-time index among {r['counts']['eligible']} eligible "
            f"window(s): {w['label']} — index {_fmt_idx(w['pm25_index'])}, peak forecast "
            f"US AQI {w['peak_aqi']} ({w['peak_category']['label']})."
        )
        if w["peak_category"]["key"] not in ("good",):
            lines.append(
                f"This window meets your planning threshold (peak AQI ≤ {th}) but is still "
                f"classified “{w['peak_category']['label']}”. Meeting a threshold does not "
                f"mean conditions are safe."
            )
    elif r["status"] == "no_eligible_window":
        w = r["least_polluted_available"]
        lines.append(
            f"No complete window in your permitted hours has a peak forecast US AQI at or "
            f"below your threshold of {th}."
        )
        lines.append(
            f"Least-polluted available window: {w['label']} — index {_fmt_idx(w['pm25_index'])}, "
            f"peak US AQI {w['peak_aqi']} ({w['peak_category']['label']}). It exceeds your "
            f"threshold and is not a safe window; consider an indoor alternative."
        )
    elif r["status"] == "no_complete_window":
        lines.append(
            "Every future window in your permitted hours touches a forecast interval with "
            "missing PM2.5 or US AQI, so no window is ranked."
        )
    else:
        lines.append("All candidate windows for this day have already started.")

    if b["complete"]:
        notes = []
        if not b["in_allowed_hours"]:
            notes.append("outside your permitted hours")
        if b["starts_in_past"]:
            notes.append("already started")
        if not b["meets_threshold"]:
            notes.append(f"above your threshold of {th}")
        suffix = f" (note: {', '.join(notes)})" if notes else ""
        lines.append(
            f"Your planned slot {b['label']}: index {_fmt_idx(b['pm25_index'])}, peak US AQI "
            f"{b['peak_aqi']} ({b['peak_category']['label']}){suffix}."
        )
    else:
        lines.append(f"Your planned slot {b['label']} has missing forecast data and cannot be scored.")

    if c["available"]:
        if c["same_window"]:
            lines.append("Your planned slot is already the lowest-index window; no change is suggested.")
        else:
            pct = c["pct_change"]
            target = "recommended" if c["chosen_is_eligible"] else "least-polluted available"
            if pct < 0:
                lines.append(
                    f"The {target} window has a {abs(pct):.1f}% lower PM2.5 pollution-time "
                    f"index than your planned slot ({c['abs_change']:+.1f} {INDEX_UNITS})."
                )
            elif pct > 0:
                lines.append(
                    f"The {target} window has a {pct:.1f}% higher PM2.5 pollution-time index "
                    f"than your planned slot; it is suggested only because your slot does not "
                    f"satisfy the constraints listed above."
                )
            else:
                lines.append(f"The {target} window has the same PM2.5 pollution-time index as your planned slot.")
    elif c["reason"]:
        lines.append(c["reason"])

    lines.append(
        "The index is a comparative planning number (forecast PM2.5 × time). It is not inhaled "
        "dose or a medical risk estimate, and rescheduling changes when you are outdoors — it "
        "does not reduce ambient pollution."
    )
    return lines
