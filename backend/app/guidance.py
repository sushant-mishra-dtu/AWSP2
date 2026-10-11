"""School outdoor-activity guidance excerpts, keyed by US AQI category.

Source: U.S. EPA / AirNow, "Air Quality and Outdoor Activity Guidance for
Schools" (School Flag Program, EPA-456/F-14-003, August 2014), retrieved
2026-10-11. This is US AQI guidance, not an Indian government directive;
local official restrictions take precedence over anything AirWindow shows.
The AirNow table has no separate "Hazardous" row; for Hazardous and
Beyond-AQI values we show its most restrictive row (Very Unhealthy).
"""

from __future__ import annotations

SOURCE = {
    "title": "Air Quality and Outdoor Activity Guidance for Schools (School Flag Program)",
    "publisher": "U.S. EPA / AirNow",
    "document": "EPA-456/F-14-003, August 2014",
    "page_url": "https://www.airnow.gov/publications/air-quality-flag-program-getting-started/air-quality-and-outdoor-activity-guidance-for-schools-flag-program/",
    "pdf_url": "https://document.airnow.gov/air-quality-and-outdoor-guidance-for-schools.pdf",
    "standard": "US AQI",
    "scope_note": "US AQI guidance from AirNow (US EPA). It is not an Indian government directive. "
    "Local official restrictions and school health policies take precedence.",
}

_TEXT = {
    "good": "Great day to be active outside.",
    "moderate": "Good day to be active outside. Students who are unusually sensitive to air pollution could have symptoms.",
    "usg": "OK to be active outside, especially for short activities such as recess and PE. For longer activities such as "
    "athletic practice, take more breaks and do less intense activities. Watch for symptoms; students with asthma "
    "should follow their asthma action plans.",
    "unhealthy": "For all outdoor activities, take more breaks and do less intense activities. Consider moving longer or "
    "more intense activities indoors or rescheduling them to another day or time. Watch for symptoms; students with "
    "asthma should follow their asthma action plans.",
    "very_unhealthy": "Move all activities indoors or reschedule them to another day.",
}

INDOOR_NOTE = (
    "Indoor air quality is unverified: AirWindow has no indoor measurements for this campus. AirNow notes that indoor "
    "particle levels are lower only when a properly installed and maintained filtration system is in place."
)


def for_category(key: str | None) -> dict:
    row = key
    note = None
    if key in ("hazardous", "beyond"):
        row = "very_unhealthy"
        note = "The AirNow school table has no separate Hazardous row; its most restrictive row is shown."
    text = _TEXT.get(row or "")
    if text is None:
        return {"available": False, "text": "No guidance shown: the forecast value is unavailable.", "source": SOURCE}
    return {"available": True, "row": row, "text": text, "note": note, "source": SOURCE}
