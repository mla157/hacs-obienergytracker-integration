"""Data update coordinator for Obi EnergyTracker."""

from __future__ import annotations

from datetime import datetime, timedelta
import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import STANDBY_INTERVALS, ObiEnergyTrackerAPI
from .const import DOMAIN, LIVE_TIMEOUT
from .live import ObiLiveMode

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(minutes=5)
DAYS_OF_HISTORY = 7


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

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from API.

        Retrieves:
        - Meter reading (Zählerstand) for the device
        - Hourly energy data for the past 7 days
        - Consumption forecast and standby power, both best-effort
        """
        try:
            meter = await self.api.async_get_meter_data()
            _LOGGER.debug("Meter data: %s", meter)

            device = await self.api.async_get_device_info()
            _LOGGER.debug("Device data: %s", device)

            # Fetch hourly data for past days (default 7 days)
            end_date = datetime.now()
            hourly_data = await self.api.async_get_hourly_data(
                start_date=end_date,
                num_days=DAYS_OF_HISTORY,
            )
            _LOGGER.debug(
                "Hourly data fetched: %s", "available" if hourly_data else "none"
            )

            _LOGGER.info(
                "Successfully fetched data: meter=%s, device=%s, hourly_days=%d",
                "available" if meter else "none",
                "available" if device else "none",
                DAYS_OF_HISTORY,
            )
        except OSError as err:
            _LOGGER.error("Failed to update data: %s", err)
            raise UpdateFailed(f"Failed to update data: {err}") from err

        # Analytics are supplementary: the API client returns None on failure
        # so that a missing forecast never takes the meter sensors down.
        forecast = await self.api.async_get_consumption_forecast() or {}

        standby = {
            interval: await self.api.async_get_standby_power(interval)
            for interval in STANDBY_INTERVALS
        }

        return {
            "hourly": hourly_data,
            "meter": meter,
            "device": device,
            "forecast": forecast,
            "standby": standby,
        }
