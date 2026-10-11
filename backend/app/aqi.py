"""US AQI classification (pure, no I/O).

Rounding rule for decimal inputs
--------------------------------
US AQI is reported as a whole number. Decimal inputs are rounded half-up to
the nearest integer *before* classification (50.4 -> 50 "Good",
50.5 -> 51 "Moderate", 500.5 -> 501 "Beyond AQI").

Negative, NaN, infinite, boolean, missing (None) or non-numeric inputs are
classified as "Unavailable". The negativity check happens before rounding, so
-0.2 is Unavailable rather than 0.

This module only classifies an AQI value that a provider already calculated.
It never derives AQI from concentrations.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class AqiCategory:
    key: str
    label: str
    color: str
    text_color: str
    aqi: int | None
    lower: int | None
    upper: int | None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


# (key, label, lower, upper, background colour, text colour)
# Colours follow the US EPA AirNow palette.
_BANDS: tuple[tuple[str, str, int, int, str, str], ...] = (
    ("good", "Good", 0, 50, "#00e400", "#0b2e0b"),
    ("moderate", "Moderate", 51, 100, "#ffff00", "#3a3500"),
    ("usg", "Unhealthy for sensitive groups", 101, 150, "#ff7e00", "#2b1400"),
    ("unhealthy", "Unhealthy", 151, 200, "#ff0000", "#ffffff"),
    ("very_unhealthy", "Very unhealthy", 201, 300, "#8f3f97", "#ffffff"),
    ("hazardous", "Hazardous", 301, 500, "#7e0023", "#ffffff"),
)

BEYOND = ("beyond", "Beyond AQI", "#3d0011", "#ffffff")
UNAVAILABLE = ("unavailable", "Unavailable", "#9ca3af", "#111827")


def round_aqi(value: Any) -> int | None:
    """Round a provider AQI value half-up. Returns None for invalid input."""
    if value is None or isinstance(value, bool):
        return None
    if not isinstance(value, (int, float)):
        return None
    v = float(value)
    if math.isnan(v) or math.isinf(v) or v < 0:
        return None
    return int(math.floor(v + 0.5))


def classify_us_aqi(value: Any) -> AqiCategory:
    aqi = round_aqi(value)
    if aqi is None:
        key, label, color, text = UNAVAILABLE
        return AqiCategory(key, label, color, text, None, None, None)
    for key, label, lower, upper, color, text in _BANDS:
        if lower <= aqi <= upper:
            return AqiCategory(key, label, color, text, aqi, lower, upper)
    key, label, color, text = BEYOND
    return AqiCategory(key, label, color, text, aqi, 501, None)


def legend() -> list[dict[str, Any]]:
    items = [
        {"key": k, "label": lbl, "lower": lo, "upper": hi, "color": c, "text_color": t}
        for k, lbl, lo, hi, c, t in _BANDS
    ]
    items.append(
        {"key": BEYOND[0], "label": BEYOND[1], "lower": 501, "upper": None,
         "color": BEYOND[2], "text_color": BEYOND[3]}
    )
    items.append(
        {"key": UNAVAILABLE[0], "label": UNAVAILABLE[1], "lower": None, "upper": None,
         "color": UNAVAILABLE[2], "text_color": UNAVAILABLE[3]}
    )
    return items
