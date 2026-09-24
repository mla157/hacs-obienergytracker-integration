"""Live mode for Obi EnergyTracker.

Live mode is not a stream you simply subscribe to: the sensor has to be told
to upload every two seconds, and only then does the backend forward its
readings over a websocket. Because that sensor runs on a battery, the upload
interval must be put back to its idle value afterwards - reliably, including
when Home Assistant shuts down or the connection dies.

The stream itself is a websocket at api.obi.com that delivers frames of the
shape {"event": "mqttMessage", "data": {"power": 506, "rssi": -75,
"battery": 56}}, with the power value in watts.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
import json
import logging
from typing import Any

import aiohttp

from homeassistant.core import HomeAssistant, callback

from .api import ObiEnergyTrackerAPI
from .const import IDLE_UPLOAD_INTERVAL, LIVE_UPLOAD_INTERVAL

_LOGGER = logging.getLogger(__name__)

# Wait this long between reconnect attempts while live mode stays switched on.
RECONNECT_DELAY = 5.0

# Shorter pause after the server closed the socket cleanly. Without it, a
# server that closes straight away would turn reconnecting into a hot loop.
RECONNECT_PAUSE = 2.0

# Give up after this many consecutive failures rather than hammering the API.
MAX_FAILURES = 5

# Longest a silent websocket may block the loop. Bounding the receive is what
# lets the timeout fire even when no frames arrive at all.
POLL_INTERVAL = 5.0


def _parse_frame(raw: str) -> dict[str, Any] | None:
    """Return the data payload of a live frame, or None if unusable."""
    try:
        parsed = json.loads(raw)
    except ValueError:
        _LOGGER.debug("Live frame is not JSON: %s", raw[:120])
        return None

    if not isinstance(parsed, dict):
        return None

    data = parsed.get("data")
    return data if isinstance(data, dict) else None


class ObiLiveMode:
    """Own the live websocket and the sensor's upload interval."""

    def __init__(
        self,
        hass: HomeAssistant,
        api: ObiEnergyTrackerAPI,
        timeout: int,
    ) -> None:
        """Initialize the live mode controller."""
        self.hass = hass
        self.api = api
        self.timeout = timeout

        self.is_on = False
        self.connected = False
        self.power: float | None = None
        self.rssi: int | None = None
        self.battery: int | None = None
        self.last_error: str | None = None

        self._task: asyncio.Task[None] | None = None
        self._listeners: list[Callable[[], None]] = []

    @callback
    def async_add_listener(self, update: Callable[[], None]) -> Callable[[], None]:
        """Register an entity for updates and return a remove callback."""
        self._listeners.append(update)

        def _remove() -> None:
            if update in self._listeners:
                self._listeners.remove(update)

        return _remove

    @callback
    def _notify(self) -> None:
        """Push the current values to every registered entity."""
        for update in list(self._listeners):
            update()

    async def async_turn_on(self) -> None:
        """Start live mode if it is not already running."""
        if self._task and not self._task.done():
            return

        self.is_on = True
        self.last_error = None
        self._notify()
        self._task = self.hass.async_create_task(self._async_run())

    async def async_turn_off(self) -> None:
        """Stop live mode and wait for the upload interval to be restored."""
        self.is_on = False
        task = self._task

        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                # Expected: _async_run resets the interval in its finally
                # block before the cancellation propagates.
                pass

        self._task = None
        self.connected = False
        self.power = None
        self._notify()

    async def _async_run(self) -> None:
        """Drive live mode until it is switched off, times out or gives up."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.timeout if self.timeout else None
        failures = 0

        try:
            if not await self.api.async_set_upload_interval(LIVE_UPLOAD_INTERVAL):
                self.last_error = (
                    "Could not switch the sensor to its live upload interval"
                )
                _LOGGER.error("%s", self.last_error)
                self.is_on = False
                self._notify()
                return

            while self.is_on and failures < MAX_FAILURES:
                if deadline is not None and loop.time() >= deadline:
                    _LOGGER.debug("Live mode timed out after %ds", self.timeout)
                    self.is_on = False
                    break

                try:
                    await self._async_listen(deadline)
                    failures = 0
                    if self.is_on:
                        # Reached only when the socket closed on its own, so
                        # pace the reconnect instead of retrying immediately.
                        await asyncio.sleep(RECONNECT_PAUSE)
                except asyncio.CancelledError:
                    raise
                except (OSError, aiohttp.ClientError) as err:
                    failures += 1
                    self.last_error = f"{type(err).__name__}: {err}"
                    _LOGGER.warning(
                        "Live connection lost (%d/%d): %s",
                        failures,
                        MAX_FAILURES,
                        err,
                    )
                    self.connected = False
                    self._notify()
                    if self.is_on:
                        await asyncio.sleep(RECONNECT_DELAY)

            if failures >= MAX_FAILURES:
                _LOGGER.error("Giving up on live mode after %d failures", failures)
                self.is_on = False

        finally:
            self.connected = False
            self.power = None
            # Runs on cancellation too, and must not be cancelled itself -
            # otherwise the sensor keeps uploading every two seconds.
            await asyncio.shield(
                self.api.async_set_upload_interval(IDLE_UPLOAD_INTERVAL)
            )
            self._notify()

    async def _async_listen(self, deadline: float | None) -> None:
        """Hold one websocket connection and apply the frames it delivers."""
        loop = asyncio.get_running_loop()

        async with self.api.live_ws_connect() as websocket:
            self.connected = True
            self.last_error = None
            self._notify()
            _LOGGER.debug("Live websocket open")

            while self.is_on:
                if deadline is not None and loop.time() >= deadline:
                    self.is_on = False
                    return

                try:
                    message = await asyncio.wait_for(
                        websocket.receive(), timeout=POLL_INTERVAL
                    )
                except (TimeoutError, asyncio.TimeoutError):
                    # A quiet socket must not outlive the timeout, otherwise
                    # the sensor keeps uploading every two seconds forever.
                    # Both names are the same class from Python 3.11 on.
                    continue

                if message.type is aiohttp.WSMsgType.TEXT:
                    self._apply(_parse_frame(message.data))
                elif message.type in (
                    aiohttp.WSMsgType.CLOSE,
                    aiohttp.WSMsgType.CLOSED,
                    aiohttp.WSMsgType.CLOSING,
                    aiohttp.WSMsgType.ERROR,
                ):
                    _LOGGER.debug("Live websocket closed: %s", message.type.name)
                    return

    @callback
    def _apply(self, data: dict[str, Any] | None) -> None:
        """Take the values of one frame and tell the entities about them."""
        if not data:
            return

        power = data.get("power")
        if isinstance(power, (int, float)) and not isinstance(power, bool):
            self.power = float(power)

        rssi = data.get("rssi")
        if isinstance(rssi, int) and not isinstance(rssi, bool):
            self.rssi = rssi

        battery = data.get("battery")
        if isinstance(battery, int) and not isinstance(battery, bool):
            self.battery = battery

        self._notify()
