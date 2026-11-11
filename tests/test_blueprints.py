"""The shipped blueprints: valid, and doing what their descriptions say."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import PropertyMock, patch

from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant_custom_component.common import async_mock_service

from homeassistant.components.automation.config import AUTOMATION_BLUEPRINT_SCHEMA
from homeassistant.components.blueprint import models
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util, yaml as yaml_util

FOLDER = Path(__file__).parents[1] / "blueprints" / "automation"
BLUEPRINTS = sorted((FOLDER / "sugarsense").glob("*.yaml"))

ZONE = "sensor.sugar_sense_zone"
GLUCOSE = "sensor.sugar_sense_glucose"
TREND = "sensor.sugar_sense_trend"
IN_RANGE = "binary_sensor.sugar_sense_in_range"


def test_three_blueprints_ship():
    assert [p.name for p in BLUEPRINTS] == ["announce_low.yaml", "night_light.yaml", "zone_light.yaml"]


@pytest.mark.parametrize("path", BLUEPRINTS, ids=lambda p: p.name)
def test_blueprint_is_valid(path: Path):
    data = yaml_util.load_yaml_dict(str(path))
    blueprint = models.Blueprint(data, expected_domain="automation", schema=AUTOMATION_BLUEPRINT_SCHEMA)
    assert blueprint.name.startswith("Sugar Sense: ")
    assert blueprint.metadata["source_url"].endswith(path.name)
    # Every blueprint says what it is not.
    assert "Alerts stay on your phone." in blueprint.metadata["description"]
    text = path.read_text()
    assert chr(8212) not in text and chr(8211) not in text


async def _automation(hass: HomeAssistant, name: str, inputs: dict) -> None:
    """Create one automation from a shipped blueprint."""
    with patch.object(models.DomainBlueprints, "blueprint_folder", new_callable=PropertyMock, return_value=FOLDER):
        await _setup(hass, name, inputs)


async def _setup(hass: HomeAssistant, name: str, inputs: dict) -> None:
    assert await async_setup_component(
        hass,
        "automation",
        {"automation": {"use_blueprint": {"path": f"sugarsense/{name}", "input": inputs}}},
    )
    await hass.async_block_till_done()
    assert len(hass.states.async_entity_ids("automation")) == 1


async def test_zone_light_colors_each_zone_and_obeys_the_no_reading_choice(hass: HomeAssistant) -> None:
    on = async_mock_service(hass, "light", "turn_on")
    off = async_mock_service(hass, "light", "turn_off")
    hass.states.async_set(ZONE, "in_range")
    await _automation(hass, "zone_light.yaml", {
        "zone_sensor": ZONE, "light_target": {"entity_id": "light.desk"}, "no_reading": "off",
    })
    for zone, color in (("low", [229, 72, 77]), ("very_low", [229, 72, 77]), ("in_range", [98, 181, 67]),
                        ("high", [253, 141, 56]), ("very_high", [253, 141, 56])):
        hass.states.async_set(ZONE, zone)
        await hass.async_block_till_done()
        assert on[-1].data["rgb_color"] == color, zone
        assert on[-1].data["brightness_pct"] == 40
        assert on[-1].data["entity_id"] == ["light.desk"]
    assert not off
    # No current reading: the light goes off, because that was the choice.
    hass.states.async_set(ZONE, "unavailable")
    await hass.async_block_till_done()
    assert len(off) == 1 and len(on) == 5


async def test_zone_light_leaves_the_light_alone_without_a_reading_by_default(hass: HomeAssistant) -> None:
    on = async_mock_service(hass, "light", "turn_on")
    off = async_mock_service(hass, "light", "turn_off")
    hass.states.async_set(ZONE, "in_range")
    await _automation(hass, "zone_light.yaml", {"zone_sensor": ZONE, "light_target": {"entity_id": "light.desk"}})
    hass.states.async_set(ZONE, "unavailable")
    await hass.async_block_till_done()
    assert not on and not off


def _announce_inputs(**extra):
    return {
        "zone_sensor": ZONE, "glucose_sensor": GLUCOSE, "trend_sensor": TREND,
        "tts_entity": "tts.home", "speaker": "media_player.kitchen", **extra,
    }


async def test_announce_low_speaks_once_on_entering_low(hass: HomeAssistant) -> None:
    speak = async_mock_service(hass, "tts", "speak")
    hass.states.async_set(ZONE, "in_range")
    hass.states.async_set(GLUCOSE, "68")
    hass.states.async_set(TREND, "falling")
    await _automation(hass, "announce_low.yaml", _announce_inputs())
    hass.states.async_set(ZONE, "low")
    await hass.async_block_till_done()
    assert len(speak) == 1
    assert speak[0].data["message"] == "Glucose is 68 and falling."
    assert speak[0].data["media_player_entity_id"] == "media_player.kitchen"
    assert speak[0].data["entity_id"] == ["tts.home"]
    # Sliding from low to very low is the same episode: nothing more is said.
    hass.states.async_set(ZONE, "very_low")
    await hass.async_block_till_done()
    assert len(speak) == 1
    # Back in range and low again: a new episode.
    hass.states.async_set(ZONE, "in_range")
    hass.states.async_set(ZONE, "low")
    await hass.async_block_till_done()
    assert len(speak) == 2
    # A restart or a data gap in the middle of a low is not a new low.
    hass.states.async_set(ZONE, "unavailable")
    hass.states.async_set(ZONE, "low")
    await hass.async_block_till_done()
    assert len(speak) == 2
    # A high says nothing.
    hass.states.async_set(ZONE, "high")
    await hass.async_block_till_done()
    assert len(speak) == 2


@pytest.mark.parametrize(
    ("clock", "spoken"),
    [("23:30:00", 0), ("03:00:00", 0), ("06:59:59", 0), ("07:00:00", 1), ("12:00:00", 1), ("21:59:59", 1)],
)
async def test_announce_low_stays_quiet_in_its_quiet_hours(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, clock: str, spoken: int
) -> None:
    await hass.config.async_set_time_zone("UTC")
    freezer.move_to(f"2026-11-11 {clock}+00:00")
    speak = async_mock_service(hass, "tts", "speak")
    hass.states.async_set(ZONE, "in_range")
    hass.states.async_set(GLUCOSE, "3.6")
    hass.states.async_set(TREND, "falling_fast")
    await _automation(hass, "announce_low.yaml", _announce_inputs(quiet_from="22:00:00", quiet_until="07:00:00"))
    hass.states.async_set(ZONE, "very_low")
    await hass.async_block_till_done()
    assert len(speak) == spoken
    if spoken:
        assert speak[0].data["message"] == "Glucose is 3.6 and falling fast."


@pytest.mark.parametrize(("clock", "lit"), [("23:00:00", 1), ("02:00:00", 1), ("12:00:00", 0)])
async def test_night_light_only_at_night_and_off_when_back_in_range(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, clock: str, lit: int
) -> None:
    await hass.config.async_set_time_zone("UTC")
    freezer.move_to(f"2026-11-11 {clock}+00:00")
    on = async_mock_service(hass, "light", "turn_on")
    off = async_mock_service(hass, "light", "turn_off")
    hass.states.async_set(IN_RANGE, "on")
    await _automation(hass, "night_light.yaml", {"in_range_sensor": IN_RANGE, "light_target": {"entity_id": "light.hall"}})
    hass.states.async_set(IN_RANGE, "off")
    await hass.async_block_till_done()
    assert len(on) == lit
    if lit:
        assert on[0].data["brightness_pct"] == 15
    hass.states.async_set(IN_RANGE, "on")
    await hass.async_block_till_done()
    # By day the light is never touched, in either direction.
    assert len(off) == lit


async def test_night_light_lights_when_the_night_begins_out_of_range_and_goes_off_in_the_morning(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    from pytest_homeassistant_custom_component.common import async_fire_time_changed

    await hass.config.async_set_time_zone("UTC")
    freezer.move_to("2026-11-11 21:40:00+00:00")
    on = async_mock_service(hass, "light", "turn_on")
    off = async_mock_service(hass, "light", "turn_off")
    hass.states.async_set(IN_RANGE, "on")
    await _automation(hass, "night_light.yaml", {"in_range_sensor": IN_RANGE, "light_target": {"entity_id": "light.hall"}})
    hass.states.async_set(IN_RANGE, "off")       # low at 21:40, before the night
    await hass.async_block_till_done()
    assert not on
    freezer.move_to("2026-11-11 22:00:01+00:00")
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert len(on) == 1, "the night began with glucose already out of range"
    freezer.move_to("2026-11-12 07:00:01+00:00")
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert len(off) == 1, "the night ended while still out of range"


async def test_night_light_leaves_the_morning_alone_when_in_range(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    from pytest_homeassistant_custom_component.common import async_fire_time_changed

    await hass.config.async_set_time_zone("UTC")
    freezer.move_to("2026-11-12 06:55:00+00:00")
    async_mock_service(hass, "light", "turn_on")
    off = async_mock_service(hass, "light", "turn_off")
    hass.states.async_set(IN_RANGE, "on")
    await _automation(hass, "night_light.yaml", {"in_range_sensor": IN_RANGE, "light_target": {"entity_id": "light.hall"}})
    freezer.move_to("2026-11-12 07:00:01+00:00")
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert not off, "a lamp the person switched on themselves is not switched off"
