"""The pairing flow."""

from __future__ import annotations

from unittest.mock import patch

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.sugarsense.const import CONF_ACCOUNT_REF, CONF_SESSION_TOKEN, DOMAIN

from .conftest import ACCOUNT_REF, POLL_URL, START_URL, TOKEN, UNPAIR_URL, envelope

START = {
    "code": "KXT4M9",
    "pollSecret": "s" * 43,
    "expiresInSeconds": 600,
    "pollIntervalSeconds": 1,
    "pairUrl": "https://app.sugarsense.io/ha?c=KXT4M9",
    "pairLabel": "app.sugarsense.io/ha",
}
DONE = {"pending": False, "sessionToken": TOKEN, "accountRef": ACCOUNT_REF, "pullSeconds": 60}


async def _finish(hass: HomeAssistant, flow_id: str):
    """Submit the code form and let the wait run to its end."""
    with patch("custom_components.sugarsense.config_flow.asyncio.sleep", return_value=None):
        result = await hass.config_entries.flow.async_configure(flow_id, {})
        await hass.async_block_till_done()
        while result["type"] in (FlowResultType.SHOW_PROGRESS, FlowResultType.SHOW_PROGRESS_DONE):
            result = await hass.config_entries.flow.async_configure(flow_id)
            await hass.async_block_till_done()
    return result


async def test_pairing_shows_the_code_then_creates_the_entry(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.post(START_URL, json=envelope(START))
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "pair"
    assert result["description_placeholders"]["code"] == "KXT-4M9"
    assert result["description_placeholders"]["url"] == START["pairUrl"]

    # Not connected on the first poll, connected on the second.
    aioclient_mock.post(POLL_URL, side_effect=None, json=envelope({"pending": True}))
    polls = []

    async def poll(method, url, data):
        polls.append(data)
        from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMockResponse
        answer = {"pending": True} if len(polls) == 1 else DONE
        return AiohttpClientMockResponse(method, url, json=envelope(answer))

    aioclient_mock.clear_requests()
    aioclient_mock.post(POLL_URL, side_effect=poll)
    with patch("custom_components.sugarsense.async_setup_entry", return_value=True):
        result = await _finish(hass, result["flow_id"])
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Sugar Sense"
    assert result["data"] == {CONF_SESSION_TOKEN: TOKEN, CONF_ACCOUNT_REF: ACCOUNT_REF}
    assert result["result"].unique_id == ACCOUNT_REF
    assert len(polls) == 2


async def test_poll_tells_the_server_what_is_connecting_without_the_installation_id(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.post(START_URL, json=envelope(START))
    aioclient_mock.post(POLL_URL, json=envelope(DONE))
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    with patch("custom_components.sugarsense.async_setup_entry", return_value=True):
        await _finish(hass, result["flow_id"])
    body = aioclient_mock.mock_calls[-1][2]
    assert body["pollSecret"] == START["pollSecret"]
    assert body["deviceId"].startswith("ha-") and len(body["deviceId"]) == 19
    from homeassistant.helpers import instance_id
    assert await instance_id.async_get(hass) not in body["deviceId"]
    assert body["label"]
    assert body["integrationVersion"] == "1.0.0"


async def test_an_expired_code_shows_a_new_one(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.post(START_URL, json=envelope(START))
    aioclient_mock.post(POLL_URL, status=404, json={"error": True, "status": 404, "response": False})
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    aioclient_mock.clear_requests()
    aioclient_mock.post(POLL_URL, status=404, json={"error": True, "status": 404, "response": False})
    aioclient_mock.post(START_URL, json=envelope({**START, "code": "NEW123", "pairUrl": "https://app.sugarsense.io/ha?c=NEW123"}))
    result = await _finish(hass, result["flow_id"])
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "pair"
    assert result["errors"] == {"base": "code_expired"}
    assert result["description_placeholders"]["code"] == "NEW-123"


async def test_no_connection_at_the_start_aborts_cleanly(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.post(START_URL, exc=TimeoutError())
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "cannot_connect"


async def test_the_server_switch_aborts_with_its_own_words(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.post(START_URL, status=503, json={"error": True, "status": 503, "response": False})
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "disabled"


async def test_the_same_account_is_not_added_twice_and_its_entry_takes_the_new_session(hass: HomeAssistant, aioclient_mock, entry) -> None:
    aioclient_mock.post(START_URL, json=envelope(START))
    aioclient_mock.post(POLL_URL, json=envelope({**DONE, "sessionToken": "n" * 43}))
    aioclient_mock.post(UNPAIR_URL, json=envelope(True))
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    with patch("custom_components.sugarsense.async_setup_entry", return_value=True):
        result = await _finish(hass, result["flow_id"])
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    # The server retired the old session when it made the new one (same home,
    # same account): the existing entry takes the new session, nothing is ended.
    assert not [c for c in aioclient_mock.mock_calls if str(c[1]) == UNPAIR_URL]
    assert entry.data[CONF_SESSION_TOKEN] == "n" * 43


async def test_reconnect_replaces_the_session_of_the_same_account(hass: HomeAssistant, aioclient_mock, entry) -> None:
    aioclient_mock.post(START_URL, json=envelope(START))
    aioclient_mock.post(POLL_URL, json=envelope({**DONE, "sessionToken": "n" * 43}))
    result = await entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["step_id"] == "pair"
    with patch("custom_components.sugarsense.async_setup_entry", return_value=True):
        result = await _finish(hass, result["flow_id"])
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_SESSION_TOKEN] == "n" * 43


async def test_reconnect_with_another_account_is_refused_and_its_link_ended(hass: HomeAssistant, aioclient_mock, entry) -> None:
    aioclient_mock.post(START_URL, json=envelope(START))
    aioclient_mock.post(POLL_URL, json=envelope({**DONE, "sessionToken": "n" * 43, "accountRef": "f" * 16}))
    aioclient_mock.post(UNPAIR_URL, json=envelope(True))
    result = await entry.start_reauth_flow(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    result = await _finish(hass, result["flow_id"])
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "wrong_account"
    assert entry.data[CONF_SESSION_TOKEN] == TOKEN
    assert any(str(c[1]) == UNPAIR_URL for c in aioclient_mock.mock_calls)


async def test_reconnect_with_an_account_configured_in_another_entry_hands_it_the_session(
    hass: HomeAssistant, aioclient_mock, entry
) -> None:
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    other = MockConfigEntry(domain=DOMAIN, title="Sugar Sense", unique_id="f" * 16,
                            data={CONF_SESSION_TOKEN: "o" * 43, CONF_ACCOUNT_REF: "f" * 16})
    other.add_to_hass(hass)
    aioclient_mock.post(START_URL, json=envelope(START))
    aioclient_mock.post(POLL_URL, json=envelope({**DONE, "sessionToken": "n" * 43, "accountRef": "f" * 16}))
    result = await entry.start_reauth_flow(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    with patch("custom_components.sugarsense.async_setup_entry", return_value=True):
        result = await _finish(hass, result["flow_id"])
    assert result["reason"] == "wrong_account"
    assert other.data[CONF_SESSION_TOKEN] == "n" * 43
    assert entry.data[CONF_SESSION_TOKEN] == TOKEN
    assert not [c for c in aioclient_mock.mock_calls if str(c[1]) == UNPAIR_URL]


async def test_a_code_confirmed_long_before_submit_is_still_redeemed(hass: HomeAssistant, aioclient_mock) -> None:
    """The code's own ten minutes are over, but the person confirmed it in time."""
    aioclient_mock.post(START_URL, json=envelope({**START, "expiresInSeconds": 1}))
    aioclient_mock.post(POLL_URL, json=envelope(DONE))
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    flow = hass.config_entries.flow._progress[result["flow_id"]]
    flow._deadline = 0          # as if the ten minutes had passed on the code form
    flow._poll_deadline = 0
    with patch("custom_components.sugarsense.async_setup_entry", return_value=True):
        result = await _finish(hass, result["flow_id"])
    assert result["type"] is FlowResultType.CREATE_ENTRY
