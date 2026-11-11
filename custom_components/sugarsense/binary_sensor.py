"""Sugar Sense binary sensors."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from . import logic
from .coordinator import SugarSenseConfigEntry
from .entity import SugarSenseEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SugarSenseConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the binary sensors of one paired account."""
    coordinator = entry.runtime_data
    async_add_entities(
        [InRangeBinarySensor(coordinator, "in_range"), AlertsPausedBinarySensor(coordinator, "alerts_paused")]
    )


class InRangeBinarySensor(SugarSenseEntity, BinarySensorEntity):
    """On while the current reading is inside the person's own range."""

    @property
    def is_on(self) -> bool | None:
        data = self.coordinator.data
        if data is None:
            return None
        zone = logic.zone(data.value_mgdl, data.limits)
        return None if zone is None else zone == logic.ZONE_IN_RANGE


class AlertsPausedBinarySensor(SugarSenseEntity, BinarySensorEntity):
    """On while the person's alerts are paused in the app (a snooze or Quiet hours)."""

    needs_fresh = False

    def _paused(self) -> bool:
        data = self.coordinator.data
        return bool(
            data
            and data.paused_until_ms is not None
            and data.paused_until_ms > self.coordinator.now_ms()
        )

    @property
    def is_on(self) -> bool | None:
        return None if self.coordinator.data is None else self._paused()

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        data = self.coordinator.data
        if data is None or not self._paused() or data.paused_until_ms is None:
            return None
        return {
            "until": dt_util.utc_from_timestamp(data.paused_until_ms / 1000).isoformat(),
            "everything": data.paused_everything,
        }
