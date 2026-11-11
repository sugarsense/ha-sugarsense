"""Diagnostics: what a bug report needs, without the session or any identity."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.core import HomeAssistant

from .const import VERSION
from .coordinator import SugarSenseConfigEntry


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: SugarSenseConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for one paired account."""
    coordinator = entry.runtime_data
    data = asdict(coordinator.data) if coordinator.data is not None else None
    if data is not None:
        # The person's name is theirs, not a bug report's.
        data["label"] = "**REDACTED**" if data.get("label") else None
    return {
        "integration_version": VERSION,
        "last_update_success": coordinator.last_update_success,
        "update_interval_seconds": coordinator.update_interval.total_seconds()
        if coordinator.update_interval
        else None,
        "fresh": coordinator.fresh,
        "snapshot": data,
    }
