"""Sugar Sense sensors."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfBloodGlucoseConcentration
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from . import logic
from .coordinator import SugarSenseConfigEntry, SugarSenseCoordinator, SugarSenseData
from .entity import SugarSenseEntity

PARALLEL_UPDATES = 0

# The value kinds a description can produce.
KIND_GLUCOSE = "glucose"      # a reading or a limit: the person's unit
KIND_CHANGE = "change"        # a difference: the person's unit, signed
KIND_PLAIN = "plain"


@dataclass(frozen=True, kw_only=True)
class SugarSenseSensorDescription(SensorEntityDescription):
    """A sensor of the snapshot."""

    value: Callable[[SugarSenseData, float], Any]
    kind: str = KIND_PLAIN
    needs_fresh: bool = False
    # False: the entity exists only once the server has sent its value.
    exists: Callable[[SugarSenseData], bool] = lambda data: True


def _timestamp(ms: float | None) -> datetime | None:
    return dt_util.utc_from_timestamp(ms / 1000) if ms and ms > 0 else None


def _limit(name: str) -> Callable[[SugarSenseData, float], Any]:
    return lambda data, now: getattr(data.limits, name) if data.limits else None


SENSORS: tuple[SugarSenseSensorDescription, ...] = (
    SugarSenseSensorDescription(
        key="glucose",
        device_class=SensorDeviceClass.BLOOD_GLUCOSE_CONCENTRATION,
        state_class=SensorStateClass.MEASUREMENT,
        kind=KIND_GLUCOSE,
        needs_fresh=True,
        value=lambda data, now: data.value_mgdl,
    ),
    SugarSenseSensorDescription(
        key="trend",
        device_class=SensorDeviceClass.ENUM,
        options=logic.TRENDS,
        needs_fresh=True,
        value=lambda data, now: logic.trend(data.trend_code),
    ),
    SugarSenseSensorDescription(
        key="change",
        state_class=SensorStateClass.MEASUREMENT,
        kind=KIND_CHANGE,
        needs_fresh=True,
        value=lambda data, now: data.change_mgdl,
    ),
    SugarSenseSensorDescription(
        key="zone",
        device_class=SensorDeviceClass.ENUM,
        options=logic.ZONES,
        needs_fresh=True,
        value=lambda data, now: logic.zone(data.value_mgdl, data.limits),
    ),
    SugarSenseSensorDescription(
        key="last_reading",
        device_class=SensorDeviceClass.TIMESTAMP,
        value=lambda data, now: _timestamp(data.reading_ms),
    ),
    SugarSenseSensorDescription(
        key="time_in_range_today",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value=lambda data, now: data.tir_today,
    ),
    SugarSenseSensorDescription(
        key="sensor_day",
        entity_category=EntityCategory.DIAGNOSTIC,
        value=lambda data, now: logic.sensor_day(data.sensor_started_ms, data.sensor_life_days, now),
    ),
    SugarSenseSensorDescription(
        key="sensor_end",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value=lambda data, now: _timestamp(data.sensor_ends_ms),
    ),
    SugarSenseSensorDescription(
        key="very_low_limit",
        device_class=SensorDeviceClass.BLOOD_GLUCOSE_CONCENTRATION,
        entity_category=EntityCategory.DIAGNOSTIC,
        kind=KIND_GLUCOSE,
        value=_limit("very_low"),
    ),
    SugarSenseSensorDescription(
        key="low_limit",
        device_class=SensorDeviceClass.BLOOD_GLUCOSE_CONCENTRATION,
        entity_category=EntityCategory.DIAGNOSTIC,
        kind=KIND_GLUCOSE,
        value=_limit("low"),
    ),
    SugarSenseSensorDescription(
        key="high_limit",
        device_class=SensorDeviceClass.BLOOD_GLUCOSE_CONCENTRATION,
        entity_category=EntityCategory.DIAGNOSTIC,
        kind=KIND_GLUCOSE,
        value=_limit("high"),
    ),
    SugarSenseSensorDescription(
        key="very_high_limit",
        device_class=SensorDeviceClass.BLOOD_GLUCOSE_CONCENTRATION,
        entity_category=EntityCategory.DIAGNOSTIC,
        kind=KIND_GLUCOSE,
        value=_limit("very_high"),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SugarSenseConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the sensors of one paired account."""
    coordinator = entry.runtime_data
    async_add_entities(SugarSenseSensor(coordinator, description) for description in SENSORS)


class SugarSenseSensor(SugarSenseEntity, SensorEntity):
    """One value of the snapshot."""

    entity_description: SugarSenseSensorDescription

    def __init__(
        self, coordinator: SugarSenseCoordinator, description: SugarSenseSensorDescription
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description
        self.needs_fresh = description.needs_fresh

    @property
    def _is_mmol(self) -> bool:
        data = self.coordinator.data
        return bool(data and data.is_mmol)

    @property
    def native_unit_of_measurement(self) -> str | None:
        """Readings, limits and the change use the person's own unit."""
        if self.entity_description.kind in (KIND_GLUCOSE, KIND_CHANGE):
            return (
                UnitOfBloodGlucoseConcentration.MILLIMOLE_PER_LITER
                if self._is_mmol
                else UnitOfBloodGlucoseConcentration.MILLIGRAMS_PER_DECILITER
            )
        return self.entity_description.native_unit_of_measurement

    @property
    def suggested_display_precision(self) -> int | None:
        if self.entity_description.kind in (KIND_GLUCOSE, KIND_CHANGE):
            return 1 if self._is_mmol else 0
        return self.entity_description.suggested_display_precision

    @property
    def native_value(self) -> Any:
        data = self.coordinator.data
        if data is None:
            return None
        raw = self.entity_description.value(data, self.coordinator.now_ms())
        kind = self.entity_description.kind
        if kind == KIND_GLUCOSE:
            return logic.display_value(raw, data.is_mmol)
        if kind == KIND_CHANGE:
            return logic.display_change(raw, data.is_mmol)
        return raw

    @property
    def icon(self) -> str | None:
        if self.entity_description.key == "trend" and self.available:
            data = self.coordinator.data
            if data is not None:
                return logic.TREND_ICONS[logic.trend(data.trend_code)]
        return super().icon

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """The reading always carries its raw mg/dL value for automations."""
        data = self.coordinator.data
        if self.entity_description.key != "glucose" or data is None or not self.available:
            return None
        return {"mgdl": logic.display_value(data.value_mgdl, False)}
