"""Shared fixtures for the Sugar Sense tests."""

from __future__ import annotations

from typing import Any

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sugarsense.const import (
    API_BASE,
    CONF_ACCOUNT_REF,
    CONF_SESSION_TOKEN,
    DOMAIN,
)

TOKEN = "t" * 43
ACCOUNT_REF = "0123456789abcdef"
SNAPSHOT_URL = f"{API_BASE}/getHaSnapshot"
START_URL = f"{API_BASE}/haPairStart"
POLL_URL = f"{API_BASE}/haPairPoll"
UNPAIR_URL = f"{API_BASE}/haUnpair"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Let Home Assistant load the integration under test."""
    return


def envelope(response: Any) -> dict[str, Any]:
    """The server's answer envelope."""
    return {"error": False, "status": 200, "response": response}


def snapshot(now_ms: float, **overrides: Any) -> dict[str, Any]:
    """A state 0 snapshot with a reading one minute old."""
    base = {
        "state": 0,
        "value": 177,
        "date": now_ms - 60_000,
        "trend": 3,
        "change": 1,
        "isMmol": False,
        "veryLowLimit": 55,
        "lowLimit": 70,
        "highLimit": 180,
        "veryHighLimit": 250,
        "pullSeconds": 60,
    }
    base.update(overrides)
    return {k: v for k, v in base.items() if v is not ...}


@pytest.fixture
def entry(hass) -> MockConfigEntry:
    """A paired account."""
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        title="Sugar Sense",
        unique_id=ACCOUNT_REF,
        data={CONF_SESSION_TOKEN: TOKEN, CONF_ACCOUNT_REF: ACCOUNT_REF},
    )
    config_entry.add_to_hass(hass)
    return config_entry
