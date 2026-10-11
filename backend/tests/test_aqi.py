import math

import pytest

from app.aqi import classify_us_aqi, legend, round_aqi


@pytest.mark.parametrize(
    "value,key,aqi",
    [
        (0, "good", 0),
        (50, "good", 50),
        (50.4, "good", 50),
        (50.5, "moderate", 51),
        (51, "moderate", 51),
        (100, "moderate", 100),
        (100.49, "moderate", 100),
        (101, "usg", 101),
        (150, "usg", 150),
        (151, "unhealthy", 151),
        (200, "unhealthy", 200),
        (201, "very_unhealthy", 201),
        (300, "very_unhealthy", 300),
        (301, "hazardous", 301),
        (500, "hazardous", 500),
        (500.4, "hazardous", 500),
        (500.5, "beyond", 501),
        (501, "beyond", 501),
        (710, "beyond", 710),
        (0.4, "good", 0),
    ],
)
def test_band_boundaries(value, key, aqi):
    c = classify_us_aqi(value)
    assert c.key == key
    assert c.aqi == aqi


def test_labels_and_colours():
    assert classify_us_aqi(42).label == "Good"
    assert classify_us_aqi(42).color == "#00e400"
    assert classify_us_aqi(120).label == "Unhealthy for sensitive groups"
    assert classify_us_aqi(250).label == "Very unhealthy"
    assert classify_us_aqi(400).color == "#7e0023"
    beyond = classify_us_aqi(612)
    assert beyond.label == "Beyond AQI"
    assert beyond.upper is None


@pytest.mark.parametrize(
    "value",
    [None, -1, -0.2, -0.0000001, math.nan, math.inf, -math.inf, "100", True, False, [], {}],
)
def test_invalid_is_unavailable(value):
    c = classify_us_aqi(value)
    assert c.key == "unavailable"
    assert c.label == "Unavailable"
    assert c.aqi is None
    assert c.color == "#9ca3af"


def test_round_half_up_not_bankers():
    # Python's round() would give 50 and 52 here (banker's rounding).
    assert round_aqi(50.5) == 51
    assert round_aqi(51.5) == 52
    assert round_aqi(-0.0) == 0


def test_legend_complete_and_ordered():
    keys = [x["key"] for x in legend()]
    assert keys == ["good", "moderate", "usg", "unhealthy", "very_unhealthy", "hazardous", "beyond", "unavailable"]
