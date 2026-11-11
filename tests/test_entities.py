"""The sensors: values, units, the 15-minute rule, the notices, reconnecting."""

from __future__ import annotations

from datetime import timedelta

from freezegun.api import FrozenDateTimeFactory
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util

from custom_components.sugarsense.const import DOMAIN

from .conftest import SNAPSHOT_URL, TOKEN, UNPAIR_URL, envelope, snapshot

S = "sensor.sugar_sense_"
B = "binary_sensor.sugar_sense_"


def now_ms() -> float:
    return dt_util.utcnow().timestamp() * 1000


async def setup(hass: HomeAssistant, entry) -> None:
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_a_fresh_reading_fills_every_sensor(hass: HomeAssistant, aioclient_mock, entry) -> None:
    aioclient_mock.post(SNAPSHOT_URL, json=envelope(snapshot(now_ms(), tirToday=63)))
    await setup(hass, entry)
    glucose = hass.states.get(f"{S}glucose")
    assert glucose.state == "177"
    assert glucose.attributes["unit_of_measurement"] == "mg/dL"
    assert glucose.attributes["mgdl"] == 177
    assert hass.states.get(f"{S}trend").state == "steady"
    assert hass.states.get(f"{S}change").state == "1"
    assert hass.states.get(f"{S}zone").state == "in_range"
    assert hass.states.get(f"{S}time_in_range_today").state == "63"
    assert hass.states.get(f"{S}low_limit").state == "70"
    assert hass.states.get(f"{S}high_limit").state == "180"
    assert hass.states.get(f"{B}in_range").state == STATE_ON
    assert hass.states.get(f"{B}alerts_paused").state == STATE_OFF
    # The request carries the session and this home's clock offset, nothing else of the home.
    call = aioclient_mock.mock_calls[-1]
    assert call[3]["Authorization"] == f"Bearer {TOKEN}"
    assert set(call[2]) == {"utcOffsetMinutes", "haVersion", "integrationVersion"}


async def test_a_mmol_person_sees_mmol_by_the_apps_own_rule(hass: HomeAssistant, aioclient_mock, entry) -> None:
    aioclient_mock.post(SNAPSHOT_URL, json=envelope(snapshot(now_ms(), isMmol=True, change=-9)))
    await setup(hass, entry)
    glucose = hass.states.get(f"{S}glucose")
    assert glucose.state == "9.8"
    assert glucose.attributes["unit_of_measurement"] == "mmol/L"
    assert glucose.attributes["mgdl"] == 177
    assert hass.states.get(f"{S}change").state == "-0.5"
    assert hass.states.get(f"{S}low_limit").state == "3.9"


async def test_on_the_high_line_is_out_of_range(hass: HomeAssistant, aioclient_mock, entry) -> None:
    aioclient_mock.post(SNAPSHOT_URL, json=envelope(snapshot(now_ms(), value=180, trend=5)))
    await setup(hass, entry)
    assert hass.states.get(f"{S}zone").state == "high"
    assert hass.states.get(f"{B}in_range").state == STATE_OFF
    assert hass.states.get(f"{S}trend").state == "rising_fast"


async def test_the_name_arrives_with_the_first_reading(hass: HomeAssistant, aioclient_mock, entry) -> None:
    aioclient_mock.post(SNAPSHOT_URL, json=envelope(snapshot(now_ms(), label="Anna")))
    await setup(hass, entry)
    assert entry.title == "Sugar Sense (Anna)"


async def test_at_fifteen_minutes_the_number_goes_unavailable_by_itself(
    hass: HomeAssistant, aioclient_mock, entry, freezer: FrozenDateTimeFactory
) -> None:
    """No pull is needed for the flip: the integration wakes itself at the exact moment."""
    reading = now_ms() - 60_000
    aioclient_mock.post(SNAPSHOT_URL, json=envelope(snapshot(now_ms(), date=reading)))
    await setup(hass, entry)
    assert hass.states.get(f"{S}glucose").state == "177"
    # From here every pull fails: the last reading must still age out on time.
    aioclient_mock.clear_requests()
    aioclient_mock.post(SNAPSHOT_URL, exc=TimeoutError())

    freezer.tick(timedelta(minutes=13, seconds=30))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get(f"{S}glucose").state == "177", "a failed pull keeps the last reading until it is stale"
    assert hass.states.get(f"{S}low_limit").state == "70", "a short outage keeps the limits"

    freezer.tick(timedelta(seconds=31))   # 15 minutes and a second after the reading
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    for key in ("glucose", "trend", "change", "zone"):
        assert hass.states.get(f"{S}{key}").state == STATE_UNAVAILABLE, key
    assert hass.states.get(f"{B}in_range").state == STATE_UNAVAILABLE
    # The last answer from the server is 14 minutes old: the limits still stand.
    assert hass.states.get(f"{S}low_limit").state == "70"
    # A minute later nothing has been heard for 15 minutes: the rest goes
    # unavailable too, instead of showing old values as current.
    freezer.tick(timedelta(seconds=61))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get(f"{S}low_limit").state == STATE_UNAVAILABLE
    assert hass.states.get(f"{B}alerts_paused").state == STATE_UNAVAILABLE


async def test_an_old_reading_from_the_server_is_never_shown_as_current(hass: HomeAssistant, aioclient_mock, entry) -> None:
    aioclient_mock.post(SNAPSHOT_URL, json=envelope(snapshot(now_ms(), date=now_ms() - 3 * 3600_000)))
    await setup(hass, entry)
    assert hass.states.get(f"{S}glucose").state == STATE_UNAVAILABLE
    assert hass.states.get(f"{S}zone").state == STATE_UNAVAILABLE
    assert hass.states.get(f"{S}last_reading").state != STATE_UNAVAILABLE


async def test_premium_needed_raises_one_notice_and_shows_no_number(hass: HomeAssistant, aioclient_mock, entry) -> None:
    aioclient_mock.post(SNAPSHOT_URL, json=envelope({"state": 1, "premiumUrl": "https://sugarsense.io/download", "pullSeconds": 300}))
    await setup(hass, entry)
    assert hass.states.get(f"{S}glucose").state == STATE_UNAVAILABLE
    # A link that shows no reading knows nothing about the pause either.
    assert hass.states.get(f"{B}alerts_paused").state == STATE_UNAVAILABLE
    registry = ir.async_get(hass)
    issue = registry.async_get_issue(DOMAIN, f"premium_required_{entry.entry_id}")
    assert issue is not None and issue.translation_key == "premium_required"
    assert registry.async_get_issue(DOMAIN, f"no_source_{entry.entry_id}") is None

    # Premium starts: the next pull clears the notice and fills the number.
    aioclient_mock.clear_requests()
    aioclient_mock.post(SNAPSHOT_URL, json=envelope(snapshot(now_ms())))
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert registry.async_get_issue(DOMAIN, f"premium_required_{entry.entry_id}") is None
    assert hass.states.get(f"{S}glucose").state == "177"


async def test_no_source_and_follower_only_have_their_own_notices(hass: HomeAssistant, aioclient_mock, entry) -> None:
    aioclient_mock.post(SNAPSHOT_URL, json=envelope({"state": 2, "pullSeconds": 300}))
    await setup(hass, entry)
    registry = ir.async_get(hass)
    assert registry.async_get_issue(DOMAIN, f"follower_only_{entry.entry_id}") is not None
    assert registry.async_get_issue(DOMAIN, f"no_source_{entry.entry_id}") is None
    aioclient_mock.clear_requests()
    aioclient_mock.post(SNAPSHOT_URL, json=envelope({"state": 3, "pullSeconds": 300}))
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert registry.async_get_issue(DOMAIN, f"follower_only_{entry.entry_id}") is None
    assert registry.async_get_issue(DOMAIN, f"no_source_{entry.entry_id}") is not None


async def test_alerts_paused_and_the_sensor_day(hass: HomeAssistant, aioclient_mock, entry) -> None:
    now = now_ms()
    day = 24 * 3600_000
    aioclient_mock.post(SNAPSHOT_URL, json=envelope(snapshot(
        now,
        alertsPaused={"until": now + 30 * 60_000, "everything": True},
        sensor={"startedAt": now - 8.5 * day, "lifeDays": 14, "endsAt": now + 5.5 * day},
    )))
    await setup(hass, entry)
    paused = hass.states.get(f"{B}alerts_paused")
    assert paused.state == STATE_ON
    assert paused.attributes["everything"] is True
    assert hass.states.get(f"{S}sensor_day").state == "9"
    assert hass.states.get(f"{S}sensor_ends").state != STATE_UNAVAILABLE


async def test_a_disconnected_link_asks_to_reconnect(hass: HomeAssistant, aioclient_mock, entry) -> None:
    aioclient_mock.post(SNAPSHOT_URL, status=401, json={"error": True, "status": 401, "response": "Unauthorized"})
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert [f["context"]["source"] for f in flows] == ["reauth"]


async def test_the_server_sets_the_pull_cadence_within_bounds(hass: HomeAssistant, aioclient_mock, entry) -> None:
    aioclient_mock.post(SNAPSHOT_URL, json=envelope(snapshot(now_ms(), pullSeconds=120)))
    await setup(hass, entry)
    assert entry.runtime_data.update_interval == timedelta(seconds=120)
    aioclient_mock.clear_requests()
    aioclient_mock.post(SNAPSHOT_URL, json=envelope(snapshot(now_ms(), pullSeconds=1)))
    await entry.runtime_data.async_refresh()
    assert entry.runtime_data.update_interval == timedelta(seconds=30)


async def test_removing_the_integration_ends_the_link_on_the_server(hass: HomeAssistant, aioclient_mock, entry) -> None:
    aioclient_mock.post(SNAPSHOT_URL, json=envelope(snapshot(now_ms())))
    aioclient_mock.post(UNPAIR_URL, json=envelope(True))
    await setup(hass, entry)
    await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    unpair = [c for c in aioclient_mock.mock_calls if str(c[1]) == UNPAIR_URL]
    assert len(unpair) == 1 and unpair[0][3]["Authorization"] == f"Bearer {TOKEN}"


async def test_diagnostics_carry_no_session_and_no_name(hass: HomeAssistant, aioclient_mock, entry) -> None:
    from custom_components.sugarsense.diagnostics import async_get_config_entry_diagnostics

    aioclient_mock.post(SNAPSHOT_URL, json=envelope(snapshot(now_ms(), label="Anna")))
    await setup(hass, entry)
    dump = str(await async_get_config_entry_diagnostics(hass, entry))
    assert TOKEN not in dump and "Anna" not in dump
    assert "'fresh': True" in dump
