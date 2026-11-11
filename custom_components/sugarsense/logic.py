"""The Sugar Sense display contract, ported by hand. Pure: no Home Assistant imports.

The same rules every Sugar Sense surface follows:

* glucose travels in mg/dL and is converted to mmol/L only for display (x 0.0555,
  one decimal);
* a reading older than 15 minutes is stale: nothing may show it as current;
* the in-range band EXCLUDES its edges (low < value < high);
* trends are the codes 1..5 (falling fast, falling, steady, rising, rising fast).

If a rule changes in the Sugar Sense apps, it changes here in the same release.
"""

from __future__ import annotations

from dataclasses import dataclass
import math

MGDL_TO_MMOL = 0.0555
STALE_SECONDS = 15 * 60
DAY_MS = 24 * 60 * 60 * 1000

ZONE_VERY_LOW = "very_low"
ZONE_LOW = "low"
ZONE_IN_RANGE = "in_range"
ZONE_HIGH = "high"
ZONE_VERY_HIGH = "very_high"
ZONES = [ZONE_VERY_LOW, ZONE_LOW, ZONE_IN_RANGE, ZONE_HIGH, ZONE_VERY_HIGH]

TRENDS = ["falling_fast", "falling", "steady", "rising", "rising_fast"]
TREND_ICONS = {
    "falling_fast": "mdi:arrow-down",
    "falling": "mdi:arrow-bottom-right",
    "steady": "mdi:arrow-right",
    "rising": "mdi:arrow-top-right",
    "rising_fast": "mdi:arrow-up",
}


@dataclass(frozen=True)
class Limits:
    """The person's own four limits, mg/dL."""

    very_low: float
    low: float
    high: float
    very_high: float


def _finite(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _round_half_away(value: float) -> float:
    return math.copysign(math.floor(abs(value) + 0.5), value)


def is_stale(reading_ms: object, now_ms: float) -> bool:
    """A reading with no usable time, or older than 15 minutes, is stale."""
    taken = _finite(reading_ms)
    if taken is None or taken <= 0:
        return True
    return now_ms - taken > STALE_SECONDS * 1000


def stale_at_ms(reading_ms: object) -> float | None:
    """The first instant the reading counts as stale, or None without a time."""
    taken = _finite(reading_ms)
    if taken is None or taken <= 0:
        return None
    return taken + STALE_SECONDS * 1000 + 1


def zone(value_mgdl: object, limits: Limits | None) -> str | None:
    """The zone of a reading by the person's own limits.

    The out-of-range side owns the edges: a reading ON the low or the high line
    is out of range.
    """
    value = _finite(value_mgdl)
    if value is None or limits is None:
        return None
    if value >= limits.very_high:
        return ZONE_VERY_HIGH
    if value <= limits.very_low:
        return ZONE_VERY_LOW
    if value >= limits.high:
        return ZONE_HIGH
    if value <= limits.low:
        return ZONE_LOW
    return ZONE_IN_RANGE


def trend(code: object) -> str:
    """The trend name for a code, clamped into 1..5; anything unreadable is steady."""
    number = _finite(code)
    if number is None:
        return TRENDS[2]
    index = min(5, max(1, int(number))) - 1
    return TRENDS[index]


def display_value(value_mgdl: object, is_mmol: bool) -> float | int | None:
    """The reading in the person's unit: whole mg/dL, or mmol/L to one decimal."""
    value = _finite(value_mgdl)
    if value is None:
        return None
    if is_mmol:
        return _round_half_away(value * MGDL_TO_MMOL * 10) / 10
    return int(_round_half_away(value))


def display_change(change_mgdl: object, is_mmol: bool) -> float | int | None:
    """The change since the last reading in the person's unit; a flat pair is 0."""
    change = _finite(change_mgdl)
    if change is None:
        return None
    if is_mmol:
        rounded = _round_half_away(change * MGDL_TO_MMOL * 10) / 10
        return 0.0 if rounded == 0 else rounded
    rounded_int = int(_round_half_away(change))
    return rounded_int


def sensor_day(started_ms: object, life_days: object, now_ms: float) -> int | None:
    """Day X of the sensor's life, counted from 1 and capped at the last day."""
    started = _finite(started_ms)
    life = _finite(life_days)
    if started is None or life is None or life <= 0 or now_ms < started:
        return None
    elapsed_days = int((now_ms - started) // DAY_MS)
    return int(min(life, elapsed_days + 1))


def limits_from(snapshot: dict) -> Limits | None:
    """The four limits of a snapshot, or None when one is missing or out of order."""
    values = [
        _finite(snapshot.get(key))
        for key in ("veryLowLimit", "lowLimit", "highLimit", "veryHighLimit")
    ]
    if any(v is None for v in values):
        return None
    very_low, low, high, very_high = values  # type: ignore[misc]
    if not very_low <= low < high <= very_high:
        return None
    return Limits(very_low, low, high, very_high)
