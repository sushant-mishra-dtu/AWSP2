from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from app.planner import (
    PlanInput,
    PlanInputError,
    SeriesPoint,
    evaluate_window,
    local_minutes_to_utc,
    plan,
)

UTC = timezone.utc


def series_from(start: datetime, pm: list, aqi: list | None = None) -> dict:
    aqi = aqi if aqi is not None else [100] * len(pm)
    return {start + timedelta(hours=i): SeriesPoint(p, a) for i, (p, a) in enumerate(zip(pm, aqi))}


T0 = datetime(2026, 10, 12, 0, 0, tzinfo=UTC)


# ------------------------------------------------------------- interval maths
def test_full_hour_window():
    s = series_from(T0, [10, 20, 30])
    w = evaluate_window(T0, T0 + timedelta(hours=1), s, 200)
    assert w.complete and w.pm25_index == pytest.approx(10.0)


def test_partial_overlap_two_intervals():
    s = series_from(T0, [10, 20, 30])
    w = evaluate_window(T0 + timedelta(minutes=30), T0 + timedelta(minutes=90), s, 200)
    assert w.pm25_index == pytest.approx(10 * 0.5 + 20 * 0.5)


def test_thirty_minute_window_inside_one_interval():
    s = series_from(T0, [10, 20, 30])
    w = evaluate_window(T0 + timedelta(minutes=15), T0 + timedelta(minutes=45), s, 200)
    assert w.pm25_index == pytest.approx(5.0)


def test_two_hour_window_with_quarter_offsets():
    s = series_from(T0, [10, 20, 30, 40])
    w = evaluate_window(T0 + timedelta(minutes=45), T0 + timedelta(minutes=165), s, 200)
    # 15 min of 10, 60 min of 20, 45 min of 30
    assert w.pm25_index == pytest.approx(10 * 0.25 + 20 + 30 * 0.75)


def test_peak_aqi_uses_every_touched_interval():
    s = series_from(T0, [10, 20, 30], [90, 140, 60])
    w = evaluate_window(T0 + timedelta(minutes=50), T0 + timedelta(minutes=70), s, 100)
    assert w.peak_aqi == 140
    assert not w.meets_threshold


def test_window_end_exactly_on_boundary_does_not_touch_next_interval():
    s = series_from(T0, [10, None])
    w = evaluate_window(T0, T0 + timedelta(hours=1), s, 200)
    assert w.complete


# ------------------------------------------------------------- missing data
@pytest.mark.parametrize("pm,aqi", [([10, None, 30], None), ([10, 20, 30], [100, None, 100]), ([10, float("nan"), 30], None)])
def test_missing_interval_makes_window_incomplete(pm, aqi):
    s = series_from(T0, pm, aqi)
    w = evaluate_window(T0 + timedelta(minutes=30), T0 + timedelta(minutes=90), s, 200)
    assert not w.complete
    assert w.pm25_index is None
    assert w.missing_intervals == [T0 + timedelta(hours=1)]


def test_interval_absent_from_series_is_missing():
    s = series_from(T0, [10])
    w = evaluate_window(T0, T0 + timedelta(hours=2), s, 200)
    assert not w.complete


def _input(**kw) -> PlanInput:
    base = dict(
        timezone="UTC",
        day=date(2026, 10, 12),
        allowed_start_min=0,
        allowed_end_min=4 * 60,
        duration_min=60,
        baseline_start_min=0,
        threshold_aqi=150,
    )
    base.update(kw)
    return PlanInput(**base)


NOW = datetime(2026, 10, 11, 12, 0, tzinfo=UTC)


def test_incomplete_windows_are_excluded_from_ranking():
    s = series_from(T0, [50, 5, None, 40])
    r = plan(_input(), s, NOW)
    starts = [w["start_utc"] for w in r["windows"] if w["eligible"]]
    assert all("T02" not in st for st in starts)
    # 01:00-02:00 is lowest and complete
    assert r["best"]["start_utc"] == "2026-10-12T01:00:00Z"
    assert r["counts"]["incomplete"] > 0


# ------------------------------------------------------------- ranking
def test_rank_by_index_then_peak_then_earliest():
    # Hours 0 and 2 have equal PM; hour 2 has lower AQI -> wins. Hour 1 high PM.
    s = series_from(T0, [10, 99, 10, 10], [120, 100, 80, 80])
    r = plan(_input(step_min=60), s, NOW)
    assert r["best"]["start_utc"] == "2026-10-12T02:00:00Z"
    # 02:00 and 03:00 tie on index and AQI -> earliest first; the next is 03:00
    assert r["alternatives"][0]["start_utc"] == "2026-10-12T03:00:00Z"


# ------------------------------------------------------------- thresholds
def test_no_eligible_window_never_called_safe():
    s = series_from(T0, [60, 50, 70, 80], [180, 170, 190, 200])
    r = plan(_input(threshold_aqi=100), s, NOW)
    assert r["status"] == "no_eligible_window"
    assert r["best"] is None
    least = r["least_polluted_available"]
    assert least["start_utc"] == "2026-10-12T01:00:00Z"
    assert least["eligible"] is False and least["meets_threshold"] is False
    text = " ".join(r["explanations"])
    assert "not a safe window" in text
    assert "No complete window" in text
    assert r["comparison"]["chosen_is_eligible"] is False


def test_meeting_threshold_does_not_claim_safety():
    s = series_from(T0, [60, 50, 70, 80], [180, 170, 190, 200])
    r = plan(_input(threshold_aqi=200), s, NOW)
    assert r["status"] == "ok"
    text = " ".join(r["explanations"])
    assert "does not mean conditions are safe" in text


# ------------------------------------------------------------- baseline comparison
def test_baseline_comparison_percentage():
    s = series_from(T0, [80, 40, 60, 70])
    r = plan(_input(baseline_start_min=0), s, NOW)
    c = r["comparison"]
    assert r["baseline"]["pm25_index"] == pytest.approx(80)
    assert r["best"]["pm25_index"] == pytest.approx(40)
    assert c["available"] and c["pct_change"] == pytest.approx(-50.0)
    assert c["abs_change"] == pytest.approx(-40.0)


def test_baseline_same_as_best_reports_no_change():
    s = series_from(T0, [10, 40, 60, 70])
    r = plan(_input(baseline_start_min=0), s, NOW)
    assert r["comparison"]["same_window"] is True
    assert r["comparison"]["pct_change"] == 0
    assert any("no change is suggested" in x for x in r["explanations"])


def test_incomplete_baseline_gives_no_percentage():
    s = series_from(T0, [None, 40, 60, 70])
    r = plan(_input(baseline_start_min=0), s, NOW)
    assert r["comparison"]["available"] is False
    assert r["comparison"]["pct_change"] is None
    assert "missing" in r["comparison"]["reason"]


def test_zero_baseline_index_gives_no_percentage():
    s = series_from(T0, [0, 40, 60, 70])
    r = plan(_input(baseline_start_min=0), s, NOW)
    assert r["comparison"]["available"] is False
    assert r["comparison"]["pct_change"] is None


def test_baseline_outside_allowed_hours_is_flagged_not_ranked():
    s = series_from(T0, [5, 40, 60, 70, 80, 90])
    r = plan(_input(allowed_start_min=60, allowed_end_min=240, baseline_start_min=0), s, NOW)
    assert r["baseline"]["in_allowed_hours"] is False
    assert r["baseline"]["eligible"] is False
    assert r["best"]["start_utc"] == "2026-10-12T01:00:00Z"
    # The alternative is worse than the out-of-hours baseline; reported honestly.
    assert r["comparison"]["pct_change"] > 0


# ------------------------------------------------------------- time zones
def test_half_hour_offset_timezone_partial_overlap():
    # Asia/Kolkata is UTC+05:30. Local 06:00 on 12 Oct = 00:30 UTC.
    s = series_from(T0, [10, 30, 50, 70])
    p = _input(timezone="Asia/Kolkata", allowed_start_min=6 * 60, allowed_end_min=8 * 60,
               baseline_start_min=6 * 60, step_min=30)
    r = plan(p, s, NOW)
    b = r["baseline"]
    assert b["start_utc"] == "2026-10-12T00:30:00Z"
    assert b["start_local"].startswith("2026-10-12T06:00:00+05:30")
    assert b["pm25_index"] == pytest.approx(10 * 0.5 + 30 * 0.5)
    assert b["label"] == "06:00–07:00"


def test_local_to_utc_respects_dst():
    ny = ZoneInfo("America/New_York")
    assert local_minutes_to_utc(date(2026, 7, 1), 7 * 60, ny) == datetime(2026, 7, 1, 11, tzinfo=UTC)
    assert local_minutes_to_utc(date(2026, 12, 1), 7 * 60, ny) == datetime(2026, 12, 1, 12, tzinfo=UTC)
    # 24:00 is the following local midnight
    assert local_minutes_to_utc(date(2026, 12, 1), 1440, ny) == datetime(2026, 12, 2, 5, tzinfo=UTC)


def test_dst_fall_back_day_windows_have_real_duration():
    # 2026-11-01 New York: 01:00-02:00 occurs twice. Activity duration is elapsed time.
    t0 = datetime(2026, 11, 1, 4, tzinfo=UTC)  # 00:00 EDT
    s = series_from(t0, [10] * 8)
    p = _input(timezone="America/New_York", day=date(2026, 11, 1), allowed_start_min=0,
               allowed_end_min=4 * 60, baseline_start_min=0, step_min=60)
    r = plan(p, s, datetime(2026, 10, 30, tzinfo=UTC))
    for w in r["windows"]:
        start = datetime.fromisoformat(w["start_utc"].replace("Z", "+00:00"))
        end = datetime.fromisoformat(w["end_utc"].replace("Z", "+00:00"))
        assert end - start == timedelta(hours=1)
        assert w["pm25_index"] == pytest.approx(10)


# ------------------------------------------------------------- now / validation
def test_windows_in_the_past_are_not_ranked():
    s = series_from(T0, [10, 40, 60, 70])
    now = T0 + timedelta(hours=1, minutes=10)
    r = plan(_input(baseline_start_min=0, step_min=15), s, now)
    assert r["best"]["start_utc"] >= "2026-10-12T01:15:00Z"
    assert r["baseline"]["starts_in_past"] is True


def test_all_windows_past():
    s = series_from(T0, [10, 40, 60, 70])
    r = plan(_input(), s, T0 + timedelta(days=1))
    assert r["status"] == "no_future_window"
    assert r["best"] is None and r["least_polluted_available"] is None


@pytest.mark.parametrize(
    "kw",
    [
        dict(timezone="Mars/Olympus"),
        dict(duration_min=300),
        dict(duration_min=40),
        dict(allowed_start_min=240, allowed_end_min=60),
        dict(baseline_start_min=10),
        dict(threshold_aqi=900),
    ],
)
def test_invalid_inputs_raise(kw):
    with pytest.raises(PlanInputError):
        plan(_input(**kw), series_from(T0, [10] * 4), NOW)
