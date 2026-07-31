"""Sensor platform for Obi EnergyTracker."""

from __future__ import annotations

import logging

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import ObiEnergyTrackerConfigEntry
from .const import DOMAIN, DEFAULT_DEVICE_NAME
from .coordinator import ObiEnergyTrackerCoordinator

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ObiEnergyTrackerConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensors from a config entry."""
    coordinator = config_entry.runtime_data

    sensors_data = config_entry.data.get("sensors", [])
    
    if not sensors_data and "device_id" in config_entry.data:
        sensors_data = [{
            "device_id": config_entry.data["device_id"],
            "display_name": config_entry.data.get("device_name", config_entry.title)
        }]

    sensors = []
    
    for sensor_info in sensors_data:
        sensors.append(ObiMeterReadingSensor(coordinator, sensor_info))

    async_add_entities(sensors)

class ObiEnergySensorBase(CoordinatorEntity[ObiEnergyTrackerCoordinator], SensorEntity):
    """Base class for Obi EnergyTracker sensors."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: ObiEnergyTrackerCoordinator, sensor_info: dict) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        
        self.device_id = sensor_info.get("device_id")
        display_name = sensor_info.get("display_name")
        
        if display_name:
            device_name = f"{DEFAULT_DEVICE_NAME} - {display_name}"
        else:
            device_name = DEFAULT_DEVICE_NAME
        
        self._attr_device_info = {
            "identifiers": {(DOMAIN, self.device_id)},
            "name": device_name,
            "manufacturer": "Obi",
        }

class ObiMeterReadingSensor(ObiEnergySensorBase):
    """Sensor for total meter reading (Zählerstand)."""

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_translation_key = "meter_reading"
    _attr_native_unit_of_measurement = "Wh"
    
    @property
    def unique_id(self) -> str:
        """Erzeugt eine eindeutige ID basierend auf der echten Hardware-ID."""
        return f"{DOMAIN}_{self.device_id}_meter_reading"

    def __init__(self, coordinator: ObiEnergyTrackerCoordinator, sensor_info: dict) -> None:
        """Initialize the meter reading sensor."""
        super().__init__(coordinator, sensor_info)
        self._last_native_value: float | None = None
        self._last_native_value_set = False

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle coordinator updates and suppress duplicate readings."""
        new_value = self.native_value

        if not self._last_native_value_set or new_value != self._last_native_value:
            self._last_native_value_set = True
            self._last_native_value = new_value
            self.async_write_ha_state()

    @property
    def native_value(self) -> float | None:
        """Return the meter reading value."""
        
        if not self.coordinator.data or self.device_id not in self.coordinator.data:
            return None
            
        device_data = self.coordinator.data[self.device_id]
        
        _LOGGER.debug(
            "ObiMeterReadingSensor native_value called for %s. Data: %s",
            self.device_id,
            device_data,
        )
        
        if device_data and "meter" in device_data and device_data["meter"]:
            meter_data = device_data["meter"]

            # If it's a list, get the latest record
            if isinstance(meter_data, list) and len(meter_data) > 0:
                meter_data = meter_data[-1]

            if not isinstance(meter_data, dict):
                return None

            # Look for "value" (if measure is energy) or "energy" directly
            if "energy" in meter_data:
                return meter_data["energy"]
            if "value" in meter_data and meter_data.get("measure") == "energy":
                return meter_data["value"]
            # Fallback to "value" if present
            if "value" in meter_data:
                return meter_data["value"]

        return None