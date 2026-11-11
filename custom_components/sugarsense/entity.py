"""The base entity: one device per paired account, the freshness rule."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, VERSION
from .coordinator import SugarSenseCoordinator


class SugarSenseEntity(CoordinatorEntity[SugarSenseCoordinator]):
    """An entity of one paired Sugar Sense account."""

    _attr_has_entity_name = True
    # True: the entity shows a number only while the reading is fresh (15 minutes).
    needs_fresh = True

    def __init__(self, coordinator: SugarSenseCoordinator, key: str) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._attr_unique_id = f"{entry.unique_id or entry.entry_id}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.unique_id or entry.entry_id)},
            name=entry.title,
            manufacturer="Sugar Sense",
            model="Sugar Sense account",
            sw_version=VERSION,
            entry_type=DeviceEntryType.SERVICE,
            configuration_url="https://app.sugarsense.io",
        )

    @property
    def available(self) -> bool:
        """Fresh entities follow the reading's age, not the last pull.

        A pull that fails keeps the last reading on screen until it is 15 minutes
        old; from then on nothing is shown as current.
        """
        if self.coordinator.data is None:
            return False
        if self.needs_fresh:
            return self.coordinator.fresh
        return self.coordinator.recent
