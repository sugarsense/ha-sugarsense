"""Config flow: pair with a code, the way a TV app does.

Home Assistant asks Sugar Sense for a short code, shows it with a QR code, and
the person confirms it on app.sugarsense.io with their own sign-in. No vendor
password and no Sugar Sense password is ever typed into Home Assistant.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import __version__ as HA_VERSION
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import QrCodeSelector, QrCodeSelectorConfig, QrErrorCorrectionLevel

from . import async_device_ref
from .api import (
    SugarSenseApi,
    SugarSenseDisabledError,
    SugarSenseError,
    SugarSensePairingExpiredError,
)
from .const import CONF_ACCOUNT_REF, CONF_SESSION_TOKEN, DEFAULT_TITLE, DOMAIN, VERSION

_LOGGER = logging.getLogger(__name__)

DEFAULT_POLL_SECONDS = 3
DEFAULT_EXPIRES_SECONDS = 600


def _format_code(code: str) -> str:
    """ABC123 reads better as ABC-123."""
    return f"{code[:3]}-{code[3:]}" if len(code) == 6 else code


class SugarSenseConfigFlow(ConfigFlow, domain=DOMAIN):
    """Pair one Sugar Sense account."""

    VERSION = 1

    def __init__(self) -> None:
        self._pairing: dict[str, Any] | None = None
        self._deadline: float = 0
        self._poll_deadline: float = 0
        self._task: asyncio.Task[dict[str, Any]] | None = None
        self._result: dict[str, Any] | None = None
        self._error: str | None = None

    def _api(self) -> SugarSenseApi:
        return SugarSenseApi(async_get_clientsession(self.hass))

    async def _start_pairing(self) -> str | None:
        """Ask for a fresh code. Returns an error key, or None."""
        try:
            self._pairing = await self._api().pair_start()
        except SugarSenseDisabledError:
            return "disabled"
        except SugarSenseError:
            return "cannot_connect"
        expires = self._pairing.get("expiresInSeconds")
        seconds = expires if isinstance(expires, int) and expires > 0 else DEFAULT_EXPIRES_SECONDS
        now = self.hass.loop.time()
        # The code can be CONFIRMED for this long; a confirmation restarts the
        # server's window, so the wait may run for one more window after it.
        self._deadline = now + seconds
        self._poll_deadline = now + 2 * seconds
        return None

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Start: fetch a code and show it."""
        return await self.async_step_pair()

    async def async_step_pair(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Show the code and the QR code; Submit starts the wait."""
        errors: dict[str, str] = {}
        if self._error is not None:
            errors["base"] = self._error
            self._error = None
        elif user_input is not None and self._pairing is not None:
            return await self.async_step_wait()

        if self._pairing is None or self.hass.loop.time() >= self._deadline or errors:
            error = await self._start_pairing()
            if error is not None:
                if self._pairing is None:
                    return self.async_abort(reason=error)
                errors["base"] = error

        assert self._pairing is not None
        url = self._pairing["pairUrl"]
        return self.async_show_form(
            step_id="pair",
            data_schema=vol.Schema(
                {
                    vol.Optional("qr_code"): QrCodeSelector(
                        QrCodeSelectorConfig(
                            data=url,
                            scale=6,
                            error_correction_level=QrErrorCorrectionLevel.QUARTILE,
                        )
                    )
                }
            ),
            description_placeholders={
                "code": _format_code(self._pairing["code"]),
                "url": url,
                "label": self._pairing.get("pairLabel") or url,
            },
            errors=errors,
        )

    async def _wait_for_claim(self) -> dict[str, Any]:
        """Poll until the person connects, the code expires or something breaks."""
        assert self._pairing is not None
        interval = self._pairing.get("pollIntervalSeconds")
        seconds = interval if isinstance(interval, int) and 1 <= interval <= 30 else DEFAULT_POLL_SECONDS
        details = {
            "deviceId": await async_device_ref(self.hass),
            "label": self.hass.config.location_name or "Home",
            "haVersion": HA_VERSION,
            "integrationVersion": VERSION,
        }
        api = self._api()
        failures = 0
        # Always ask at least once: the person may have confirmed the code long
        # before pressing Submit. The server says when a code is really over (404).
        while True:
            try:
                answer = await api.pair_poll(self._pairing["pollSecret"], details)
            except SugarSensePairingExpiredError:
                raise
            except SugarSenseError:
                # A hiccup must not end a pairing the person is in the middle of.
                failures += 1
                if failures >= 5:
                    raise
                answer = None
            else:
                failures = 0
            if answer is not None:
                return answer
            if self.hass.loop.time() >= self._poll_deadline:
                raise SugarSensePairingExpiredError
            await asyncio.sleep(seconds)

    async def async_step_wait(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Wait for the person to connect on the pairing page; closes by itself."""
        if self._task is None:
            self._task = self.hass.async_create_task(self._wait_for_claim(), eager_start=False)
        if not self._task.done():
            assert self._pairing is not None
            return self.async_show_progress(
                step_id="wait",
                progress_action="waiting",
                description_placeholders={
                    "code": _format_code(self._pairing["code"]),
                    "label": self._pairing.get("pairLabel") or self._pairing["pairUrl"],
                },
                progress_task=self._task,
            )
        task, self._task = self._task, None
        try:
            self._result = task.result()
        except SugarSensePairingExpiredError:
            self._error = "code_expired"
        except SugarSenseDisabledError:
            self._error = "disabled"
        except SugarSenseError:
            self._error = "cannot_connect"
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Unexpected error while pairing")
            self._error = "unknown"
        if self._error is not None:
            self._pairing = None
            return self.async_show_progress_done(next_step_id="pair")
        return self.async_show_progress_done(next_step_id="finish")

    async def async_step_finish(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Create the entry (or refresh it after a reconnect)."""
        assert self._result is not None
        token = self._result["sessionToken"]
        ref = self._result.get("accountRef")
        account_ref = ref if isinstance(ref, str) and ref else None
        data = {CONF_SESSION_TOKEN: token, CONF_ACCOUNT_REF: account_ref}

        if self.source == "reauth":
            entry = self._get_reauth_entry()
            if entry.unique_id and account_ref and entry.unique_id != account_ref:
                # The person signed in with another account. The new session is
                # that account's: if it is configured here, its entry takes the
                # new session (the server retired its old one when this one was
                # made); otherwise the session is ended, never left behind.
                await self._adopt_or_end(account_ref, data)
                return self.async_abort(reason="wrong_account")
            return self.async_update_reload_and_abort(entry, data_updates=data)

        if account_ref:
            await self.async_set_unique_id(account_ref)
            # Already connected here: the existing entry takes the new session
            # (the server retired its old one when this one was made) and reloads.
            self._abort_if_unique_id_configured(updates=data)
        return self.async_create_entry(title=DEFAULT_TITLE, data=data)

    async def _adopt_or_end(self, account_ref: str, data: dict[str, Any]) -> None:
        """Give a fresh session to the entry of its own account, or end it."""
        for other in self._async_current_entries(include_ignore=False):
            if other.unique_id == account_ref:
                self.hass.config_entries.async_update_entry(other, data={**other.data, **data})
                self.hass.config_entries.async_schedule_reload(other.entry_id)
                return
        try:
            await self._api().unpair(data[CONF_SESSION_TOKEN])
        except SugarSenseError:
            pass

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        """The link was disconnected: pair again."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Say why, then show a fresh code."""
        if user_input is None:
            return self.async_show_form(step_id="reauth_confirm")
        return await self.async_step_pair()
