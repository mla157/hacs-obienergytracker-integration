"""Sensor platform for Obi EnergyTracker."""

from __future__ import annotations

import logging

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import ObiEnergyTrackerConfigEntry
from .const import DOMAIN
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

    sensors = [
        ObiMeterReadingSensor(coordinator),
    ]

    async_add_entities(sensors)


class ObiEnergySensorBase(CoordinatorEntity[ObiEnergyTrackerCoordinator], SensorEntity):
    """Base class for Obi EnergyTracker sensors."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: ObiEnergyTrackerCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._attr_device_info = {
            "identifiers": {(DOMAIN, "obi_energy_tracker")},
            "name": "Obi EnergyTracker",
            "manufacturer": "Obi",
        }


class ObiMeterReadingSensor(ObiEnergySensorBase):
    """Sensor for total meter reading (Zählerstand)."""

    _attr_unique_id = "obi_meter_reading"
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_translation_key = "meter_reading"
    _attr_native_unit_of_measurement = "Wh"

    @property
    def native_value(self) -> float | None:
        """Return the meter reading value."""
        _LOGGER.debug(
            "ObiMeterReadingSensor native_value called. Data: %s",
            self.coordinator.data,
        )
        if (
            self.coordinator.data
            and "meter" in self.coordinator.data
            and self.coordinator.data["meter"]
        ):
            meter_data = self.coordinator.data["meter"]

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
