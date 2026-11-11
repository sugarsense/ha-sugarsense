"""The Sugar Sense API client: pairing and the one snapshot read."""

from __future__ import annotations

import asyncio
from typing import Any

import aiohttp

from .const import API_BASE, REQUEST_TIMEOUT_SECONDS


class SugarSenseError(Exception):
    """Any failure talking to Sugar Sense."""


class SugarSenseConnectionError(SugarSenseError):
    """The server could not be reached, or answered something unreadable."""


class SugarSenseAuthError(SugarSenseError):
    """The session is no longer valid: the link was disconnected."""


class SugarSenseDisabledError(SugarSenseError):
    """The service is switched off on the server (HTTP 503)."""


class SugarSenseRateLimitedError(SugarSenseError):
    """Too many requests (HTTP 429)."""


class SugarSensePairingExpiredError(SugarSenseError):
    """The pairing code expired or was already used."""


class SugarSenseApi:
    """A thin client over Home Assistant's shared aiohttp session."""

    def __init__(self, session: aiohttp.ClientSession, base_url: str = API_BASE) -> None:
        self._session = session
        self._base = base_url.rstrip("/")

    async def _post(
        self, path: str, body: dict[str, Any], bearer: str | None = None
    ) -> tuple[int, Any]:
        headers = {"Authorization": f"Bearer {bearer}"} if bearer else {}
        try:
            async with asyncio.timeout(REQUEST_TIMEOUT_SECONDS):
                async with self._session.post(
                    f"{self._base}{path}", json=body, headers=headers
                ) as response:
                    status = response.status
                    try:
                        payload = await response.json(content_type=None)
                    except (ValueError, aiohttp.ContentTypeError):
                        payload = None
        except (aiohttp.ClientError, TimeoutError) as err:
            raise SugarSenseConnectionError(str(err) or type(err).__name__) from err
        return status, payload

    @staticmethod
    def _response(status: int, payload: Any) -> dict[str, Any]:
        if status == 401:
            raise SugarSenseAuthError
        if status == 429:
            raise SugarSenseRateLimitedError
        if status == 503:
            raise SugarSenseDisabledError
        if status != 200 or not isinstance(payload, dict):
            raise SugarSenseConnectionError(f"HTTP {status}")
        response = payload.get("response")
        if not isinstance(response, dict):
            raise SugarSenseConnectionError("unexpected answer")
        return response

    async def pair_start(self) -> dict[str, Any]:
        """Ask for a pairing code. Returns code, pollSecret, pairUrl, pairLabel."""
        status, payload = await self._post("/haPairStart", {})
        response = self._response(status, payload)
        for key in ("code", "pollSecret", "pairUrl"):
            if not isinstance(response.get(key), str) or not response[key]:
                raise SugarSenseConnectionError("unexpected answer")
        return response

    async def pair_poll(
        self, poll_secret: str, details: dict[str, Any]
    ) -> dict[str, Any] | None:
        """One poll. None while the person has not connected yet."""
        status, payload = await self._post(
            "/haPairPoll", {"pollSecret": poll_secret, **details}
        )
        if status == 404:
            raise SugarSensePairingExpiredError
        response = self._response(status, payload)
        if response.get("pending") is True:
            return None
        if not isinstance(response.get("sessionToken"), str) or not response["sessionToken"]:
            raise SugarSenseConnectionError("unexpected answer")
        return response

    async def snapshot(self, token: str, details: dict[str, Any]) -> dict[str, Any]:
        """The paired account's current reading and settings."""
        status, payload = await self._post("/getHaSnapshot", details, bearer=token)
        return self._response(status, payload)

    async def unpair(self, token: str) -> None:
        """End this link on the server. Best effort: failures are the caller's to ignore."""
        await self._post("/haUnpair", {}, bearer=token)
