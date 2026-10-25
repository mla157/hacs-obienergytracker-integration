"""Data update coordinator for Obi EnergyTracker."""

from __future__ import annotations

from datetime import timedelta
import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import ObiEnergyTrackerAPI
from .const import DOMAIN, LIVE_TIMEOUT
from .live import ObiLiveMode

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(minutes=5)

# Device info (battery, online status, etc.) rarely changes and does not need
# to be fetched every poll cycle.  Re-fetch it only every 30 minutes to reduce
# the number of API calls from 3-per-cycle to ~1.
DEVICE_INFO_INTERVAL = timedelta(minutes=30)


class ObiEnergyTrackerCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Data update coordinator for Obi EnergyTracker."""

    def __init__(
        self,
        hass: HomeAssistant,
        api: ObiEnergyTrackerAPI,
        config_entry: Any,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=SCAN_INTERVAL,
            config_entry=config_entry,
        )
        self.api = api
        self.live = ObiLiveMode(hass, api, LIVE_TIMEOUT)
        self._cached_device: dict[str, Any] | None = None
        self._device_polls_remaining: int = 0

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from API.

        Retrieves:
        - Meter reading (Zählerstand) every poll cycle (5 min)
        - Device info (battery, online, RSSI) every ~30 min
        """
        try:
            meter = await self.api.async_get_meter_data()
            _LOGGER.debug("Meter data: %s", meter)

            # Re-fetch device info only when the cache has expired.
            if self._device_polls_remaining <= 0:
                new_device = await self.api.async_get_device_info()
                if new_device is not None:
                    self._cached_device = new_device
                    self._device_polls_remaining = int(
                        DEVICE_INFO_INTERVAL / SCAN_INTERVAL
                    )
                    _LOGGER.debug("Device data refreshed: %s", new_device)
                else:
                    _LOGGER.warning(
                        "Could not refresh device info; retaining cached data"
                    )
                device = self._cached_device
            else:
                device = self._cached_device
                self._device_polls_remaining -= 1
                _LOGGER.debug(
                    "Device data cached (next refresh in %d polls)",
                    self._device_polls_remaining,
                )

            _LOGGER.info(
                "Successfully fetched data: meter=%s, device=%s",
                "available" if meter else "none",
                "available" if device else "none",
            )
        except OSError as err:
            _LOGGER.error("Failed to update data: %s", err)
            raise UpdateFailed(f"Failed to update data: {err}") from err

        return {
            "meter": meter,
            "device": device,
        }
