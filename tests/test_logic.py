"""The display contract port, pinned (pure: no Home Assistant needed)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from custom_components.sugarsense import logic

FIXTURES = Path(__file__).parent / "fixtures"
LIMITS = logic.Limits(very_low=55, low=70, high=180, very_high=250)
MIN = 60_000


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (40, logic.ZONE_VERY_LOW),
        (55, logic.ZONE_VERY_LOW),   # on the very low line
        (56, logic.ZONE_LOW),
        (70, logic.ZONE_LOW),        # on the low line: OUT of range
        (71, logic.ZONE_IN_RANGE),
        (179, logic.ZONE_IN_RANGE),
        (180, logic.ZONE_HIGH),      # on the high line: OUT of range
        (249, logic.ZONE_HIGH),
        (250, logic.ZONE_VERY_HIGH),
        (400, logic.ZONE_VERY_HIGH),
    ],
)
def test_zone_edges_belong_to_the_out_of_range_side(value, expected):
    assert logic.zone(value, LIMITS) == expected


@pytest.mark.parametrize("bad", [None, "120", float("nan"), float("inf"), True])
def test_zone_of_an_unreadable_value_is_nothing(bad):
    assert logic.zone(bad, LIMITS) is None
    assert logic.zone(120, None) is None


def test_stale_is_strictly_past_fifteen_minutes():
    now = 1_800_000_000_000
    assert not logic.is_stale(now - 15 * MIN, now)        # exactly 15 minutes: still current
    assert logic.is_stale(now - 15 * MIN - 1, now)
    assert not logic.is_stale(now - MIN, now)
    assert not logic.is_stale(now + 5 * MIN, now)         # a clock a little ahead is not stale
    for bad in (0, None, -5, "x", float("nan")):
        assert logic.is_stale(bad, now)


def test_the_stale_instant_is_the_first_stale_millisecond():
    reading = 1_800_000_000_000
    at = logic.stale_at_ms(reading)
    assert not logic.is_stale(reading, at - 1)
    assert logic.is_stale(reading, at)
    assert logic.stale_at_ms(0) is None
    assert logic.stale_at_ms(None) is None


@pytest.mark.parametrize(
    ("code", "expected"),
    [(1, "falling_fast"), (2, "falling"), (3, "steady"), (4, "rising"), (5, "rising_fast"),
     (0, "falling_fast"), (9, "rising_fast"), (None, "steady"), ("4", "steady"), (float("nan"), "steady")],
)
def test_trend_codes_are_clamped(code, expected):
    assert logic.trend(code) == expected


@pytest.mark.parametrize(
    ("mgdl", "mmol"),
    [(100, 5.6), (177, 9.8), (70, 3.9), (180, 10.0), (55, 3.1), (250, 13.9), (99, 5.5), (40, 2.2)],
)
def test_mmol_is_times_0_0555_to_one_decimal(mgdl, mmol):
    assert logic.display_value(mgdl, True) == mmol
    assert logic.display_value(mgdl, False) == mgdl
    assert isinstance(logic.display_value(mgdl, False), int)


def test_an_unreadable_value_displays_nothing():
    assert logic.display_value(None, True) is None
    assert logic.display_change(None, False) is None


def _change_text(value, is_mmol):
    """The fixture's text form of a change (the apps' formatting)."""
    if value == 0:
        return "0.0" if is_mmol else "0"
    sign = "+" if value > 0 else "−"
    return f"{sign}{abs(value):.1f}" if is_mmol else f"{sign}{abs(value)}"


def test_the_change_matches_the_shared_fixture():
    """Every Sugar Sense surface runs this table; so does this port."""
    fixture = json.loads((FIXTURES / "glucose-change-cases.json").read_text())
    assert fixture["constants"]["mgdlToMmol"] == logic.MGDL_TO_MMOL
    ran = 0
    for case in fixture["cases"]:
        expect = case["expect"]
        if expect.get("partnerAgeSec") is None:
            continue
        points = case["points"]
        newest = min(points, key=lambda p: p["ageSec"])
        partner = next(p for p in points if p["ageSec"] == expect["partnerAgeSec"])
        # The server sends the difference in whole mg/dL; the unit is applied here.
        diff = round(newest["mgdl"] - partner["mgdl"])
        shown = logic.display_change(diff, case["isMmol"])
        assert _change_text(shown, case["isMmol"]) == expect["text"], case["id"]
        ran += 1
    assert ran >= 10


def test_the_fixture_copy_has_not_drifted_from_the_apps():
    """Inside the Sugar Sense repository the copy must equal the shared fixture."""
    shared = Path(__file__).parents[2] / "tools" / "fixtures" / "glucose-change-cases.json"
    if not shared.exists():
        pytest.skip("the shared fixture lives in the Sugar Sense repository")
    assert json.loads(shared.read_text()) == json.loads((FIXTURES / "glucose-change-cases.json").read_text())


def test_sensor_day_counts_from_one_and_stops_at_the_last_day():
    start = 1_800_000_000_000
    day = logic.DAY_MS
    assert logic.sensor_day(start, 14, start) == 1
    assert logic.sensor_day(start, 14, start + day - 1) == 1
    assert logic.sensor_day(start, 14, start + day) == 2
    assert logic.sensor_day(start, 14, start + 8.5 * day) == 9
    assert logic.sensor_day(start, 14, start + 30 * day) == 14
    assert logic.sensor_day(start, 14, start - 1) is None
    assert logic.sensor_day(None, 14, start) is None
    assert logic.sensor_day(start, 0, start) is None


def test_limits_must_be_complete_and_in_order():
    good = {"veryLowLimit": 55, "lowLimit": 70, "highLimit": 180, "veryHighLimit": 250}
    assert logic.limits_from(good) == LIMITS
    assert logic.limits_from({**good, "lowLimit": None}) is None
    assert logic.limits_from({**good, "lowLimit": 200}) is None
    assert logic.limits_from({}) is None
