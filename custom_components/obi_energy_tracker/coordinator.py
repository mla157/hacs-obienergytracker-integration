"""Data update coordinator for Obi EnergyTracker."""

from __future__ import annotations

from datetime import datetime, timedelta
import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import ObiEnergyTrackerAPI
from .const import DOMAIN

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

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from API for all configured sensors."""
        
        sensors = self.config_entry.data.get("sensors", [])
        
        if not sensors and "device_id" in self.config_entry.data:
            sensors = [{
                "device_id": self.config_entry.data["device_id"],
                "display_name": self.config_entry.data.get("device_name", "OBI Tracker")
            }]
            
        if not sensors:
            raise UpdateFailed("Keine Sensoren in der Konfiguration gefunden.")

        all_sensor_data = {}
        end_date = datetime.now()

        for sensor in sensors:
            device_id = sensor.get("device_id")
            if not device_id:
                continue
                
            try:
                meter = await self.api.async_get_meter_data(device_id)
                
                # Fetch hourly data for past days (default 7 days)
                hourly_data = await self.api.async_get_hourly_data(
                    device_id=device_id,
                    start_date=end_date,
                    num_days=DAYS_OF_HISTORY,
                )
                
                all_sensor_data[device_id] = {
                    "hourly": hourly_data,
                    "meter": meter,
                }
                
                _LOGGER.debug("Successfully fetched data for device %s", device_id)
            except OSError as err:
                _LOGGER.error("Failed to update data for device %s: %s", device_id, err)

        if not all_sensor_data:
            raise UpdateFailed("Fehler beim Abrufen der Daten für alle Sensoren.")

        return all_sensor_data