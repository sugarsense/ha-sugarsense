"""Sugar Sense for Home Assistant: your glucose as sensors, read-only.

Home Assistant shows and automates. It never replaces your alerts: alerts stay
on your phone.
"""

from __future__ import annotations

import hashlib
import logging

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import instance_id
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import SugarSenseApi, SugarSenseError
from .const import CONF_SESSION_TOKEN
from .coordinator import SugarSenseConfigEntry, SugarSenseCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.SENSOR]


async def async_device_ref(hass: HomeAssistant) -> str:
    """A name for this installation that is not its own id: "ha-" + 16 hex digits."""
    installation = await instance_id.async_get(hass)
    digest = hashlib.sha256(f"sugarsense:{installation}".encode()).hexdigest()
    return f"ha-{digest[:16]}"


async def async_setup_entry(hass: HomeAssistant, entry: SugarSenseConfigEntry) -> bool:
    """Set up one paired account."""
    api = SugarSenseApi(async_get_clientsession(hass))
    coordinator = SugarSenseCoordinator(hass, entry, api, await async_device_ref(hass))
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: SugarSenseConfigEntry) -> bool:
    """Unload one paired account."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        entry.runtime_data.clear_issues()
    return unloaded


async def async_remove_entry(hass: HomeAssistant, entry: SugarSenseConfigEntry) -> None:
    """The integration was removed: end the link on the server too (best effort)."""
    token = entry.data.get(CONF_SESSION_TOKEN)
    if not token:
        return
    try:
        await SugarSenseApi(async_get_clientsession(hass)).unpair(token)
    except SugarSenseError:
        _LOGGER.debug("Could not tell Sugar Sense that the link was removed")
