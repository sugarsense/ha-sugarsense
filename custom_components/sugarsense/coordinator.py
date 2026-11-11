"""The data coordinator: one snapshot a minute, the 15-minute stale flip, the notices."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import __version__ as HA_VERSION
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.event import async_track_point_in_utc_time
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from . import logic
from .api import (
    SugarSenseApi,
    SugarSenseAuthError,
    SugarSenseDisabledError,
    SugarSenseError,
    SugarSenseRateLimitedError,
)
from .const import (
    APP_URL,
    CONF_SESSION_TOKEN,
    DEFAULT_PULL_SECONDS,
    DEFAULT_TITLE,
    DOMAIN,
    ISSUE_FOLLOWER_ONLY,
    ISSUE_NO_SOURCE,
    ISSUE_PREMIUM,
    MAX_PULL_SECONDS,
    MIN_PULL_SECONDS,
    STATE_FOLLOWER_ONLY,
    STATE_NO_SOURCE,
    STATE_OK,
    STATE_PREMIUM_REQUIRED,
    VERSION,
)

_LOGGER = logging.getLogger(__name__)

type SugarSenseConfigEntry = ConfigEntry[SugarSenseCoordinator]


@dataclass(frozen=True)
class SugarSenseData:
    """One snapshot, read into the shape the entities use."""

    state: int
    value_mgdl: float | None = None
    reading_ms: float = 0
    trend_code: int = 3
    change_mgdl: float | None = None
    is_mmol: bool = False
    limits: logic.Limits | None = None
    label: str | None = None
    tir_today: int | None = None
    paused_until_ms: float | None = None
    paused_everything: bool = False
    sensor_started_ms: float | None = None
    sensor_life_days: float | None = None
    sensor_ends_ms: float | None = None

    @property
    def has_reading(self) -> bool:
        """A reading with a value and a time exists (fresh or not)."""
        return self.state == STATE_OK and self.value_mgdl is not None and self.reading_ms > 0


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def parse_snapshot(raw: dict[str, Any]) -> SugarSenseData:
    """Read the server's answer defensively: anything unreadable is simply absent."""
    state = raw.get("state")
    if state not in (STATE_OK, STATE_PREMIUM_REQUIRED, STATE_FOLLOWER_ONLY, STATE_NO_SOURCE):
        raise UpdateFailed("unexpected answer")
    if state != STATE_OK:
        return SugarSenseData(state=state)
    paused = raw.get("alertsPaused") if isinstance(raw.get("alertsPaused"), dict) else {}
    sensor = raw.get("sensor") if isinstance(raw.get("sensor"), dict) else {}
    label = raw.get("label")
    tir = _number(raw.get("tirToday"))
    return SugarSenseData(
        state=STATE_OK,
        value_mgdl=_number(raw.get("value")),
        reading_ms=_number(raw.get("date")) or 0,
        trend_code=int(_number(raw.get("trend")) or 3),
        change_mgdl=_number(raw.get("change")),
        is_mmol=raw.get("isMmol") is True,
        limits=logic.limits_from(raw),
        label=label.strip()[:60] if isinstance(label, str) and label.strip() else None,
        tir_today=int(tir) if tir is not None and 0 <= tir <= 100 else None,
        paused_until_ms=_number(paused.get("until")),
        paused_everything=paused.get("everything") is True,
        sensor_started_ms=_number(sensor.get("startedAt")),
        sensor_life_days=_number(sensor.get("lifeDays")),
        sensor_ends_ms=_number(sensor.get("endsAt")),
    )


class SugarSenseCoordinator(DataUpdateCoordinator[SugarSenseData]):
    """Pulls the snapshot and tells the entities when a reading turns stale."""

    config_entry: SugarSenseConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: SugarSenseConfigEntry,
        api: SugarSenseApi,
        device_ref: str,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(seconds=DEFAULT_PULL_SECONDS),
        )
        self._api = api
        self._device_ref = device_ref
        self._unsub_stale: list[CALLBACK_TYPE] = []
        self._last_success_ms: float = 0

    def now_ms(self) -> float:
        """The current time in epoch milliseconds."""
        return dt_util.utcnow().timestamp() * 1000

    @property
    def fresh(self) -> bool:
        """A current reading exists: the only state in which a number is shown."""
        data = self.data
        return bool(data and data.has_reading and not logic.is_stale(data.reading_ms, self.now_ms()))

    @property
    def recent(self) -> bool:
        """The server answered within the last 15 minutes with a reading to show.

        What is not "the current number" (the limits, today's percent, the pause)
        stays through a short outage, and goes unavailable with everything else
        once nothing has been heard for 15 minutes or the link shows no reading.
        """
        data = self.data
        if data is None or data.state != STATE_OK:
            return False
        return not logic.is_stale(self._last_success_ms, self.now_ms())

    async def _async_update_data(self) -> SugarSenseData:
        offset = dt_util.now().utcoffset()
        details = {
            "utcOffsetMinutes": int(offset.total_seconds() // 60) if offset is not None else 0,
            "haVersion": HA_VERSION,
            "integrationVersion": VERSION,
        }
        try:
            raw = await self._api.snapshot(self.config_entry.data[CONF_SESSION_TOKEN], details)
        except SugarSenseAuthError as err:
            raise ConfigEntryAuthFailed from err
        except SugarSenseRateLimitedError as err:
            raise UpdateFailed("asked too often, slowing down") from err
        except SugarSenseDisabledError as err:
            raise UpdateFailed("Sugar Sense for Home Assistant is paused on the server") from err
        except SugarSenseError as err:
            raise UpdateFailed(str(err) or "could not reach Sugar Sense") from err

        data = parse_snapshot(raw)
        self._last_success_ms = self.now_ms()
        pull = _number(raw.get("pullSeconds"))
        if pull is not None:
            seconds = min(MAX_PULL_SECONDS, max(MIN_PULL_SECONDS, int(pull)))
            if self.update_interval is None or self.update_interval.total_seconds() != seconds:
                self.update_interval = timedelta(seconds=seconds)
        # The entry is created before the person's name is known: name it once.
        if data.label and self.config_entry.title == DEFAULT_TITLE:
            self.hass.config_entries.async_update_entry(
                self.config_entry, title=f"{DEFAULT_TITLE} ({data.label})"
            )
        self._sync_issues(data, raw)
        self._schedule_stale_flip(data)
        return data

    def _sync_issues(self, data: SugarSenseData, raw: dict[str, Any]) -> None:
        """One clear notice for a state that shows no number; gone when it passes."""
        entry_id = self.config_entry.entry_id
        wanted = {
            ISSUE_PREMIUM: data.state == STATE_PREMIUM_REQUIRED,
            ISSUE_NO_SOURCE: data.state == STATE_NO_SOURCE,
            ISSUE_FOLLOWER_ONLY: data.state == STATE_FOLLOWER_ONLY,
        }
        premium_url = raw.get("premiumUrl")
        for key, active in wanted.items():
            issue_id = f"{key}_{entry_id}"
            if not active:
                ir.async_delete_issue(self.hass, DOMAIN, issue_id)
                continue
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                issue_id,
                is_fixable=False,
                is_persistent=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key=key,
                translation_placeholders={"account": self.config_entry.title},
                learn_more_url=premium_url
                if key == ISSUE_PREMIUM and isinstance(premium_url, str) and premium_url.startswith("https://")
                else APP_URL,
            )

    def _schedule_stale_flip(self, data: SugarSenseData) -> None:
        """Wake the entities at the exact moments something stops being current.

        Two instants: the reading turns 15 minutes old (the number goes), and
        this answer turns 15 minutes old (the rest goes, if no newer answer came).
        A failed pull does not wake the entities by itself, so both are timed.
        """
        self._cancel_stale_flip()
        now = self.now_ms()
        instants = {logic.stale_at_ms(self._last_success_ms)}
        if data.has_reading:
            instants.add(logic.stale_at_ms(data.reading_ms))

        @callback
        def _flip(_now: datetime) -> None:
            self.async_update_listeners()

        for at_ms in instants:
            if at_ms is None or at_ms <= now:
                continue
            self._unsub_stale.append(
                async_track_point_in_utc_time(
                    self.hass, _flip, dt_util.utc_from_timestamp(at_ms / 1000)
                )
            )

    def _cancel_stale_flip(self) -> None:
        for unsub in self._unsub_stale:
            unsub()
        self._unsub_stale = []

    def clear_issues(self) -> None:
        """Remove this entry's notices (the entry is unloading)."""
        for key in (ISSUE_PREMIUM, ISSUE_NO_SOURCE, ISSUE_FOLLOWER_ONLY):
            ir.async_delete_issue(self.hass, DOMAIN, f"{key}_{self.config_entry.entry_id}")

    async def async_shutdown(self) -> None:
        """Stop the stale timer with the coordinator."""
        self._cancel_stale_flip()
        await super().async_shutdown()
