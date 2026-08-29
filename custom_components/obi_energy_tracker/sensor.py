"""Sensor platform for Obi EnergyTracker."""

from __future__ import annotations

from datetime import datetime
import logging
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.core import HomeAssistant, callback
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
        ObiBatteryLevelSensor(coordinator),
        ObiIsOnlineSensor(coordinator),
        ObiConnectionStrengthSensor(coordinator),
        ObiLastRecordReceivedAtSensor(coordinator),
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

    def __init__(self, coordinator: ObiEnergyTrackerCoordinator) -> None:
        """Initialize the meter reading sensor."""
        super().__init__(coordinator)
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


class ObiDeviceValueSensorBase(ObiEnergySensorBase):
    """Base sensor for values sourced from coordinator device data."""

    _device_key: str

    @property
    def native_value(self) -> Any:
        """Return value for the configured device key."""
        if not self.coordinator.data:
            return None

        device_data = self.coordinator.data.get("device")
        if not isinstance(device_data, dict):
            return None

        return device_data.get(self._device_key)


class ObiBatteryLevelSensor(ObiDeviceValueSensorBase):
    """Sensor for battery level."""

    _attr_unique_id = "obi_battery_level"
    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_translation_key = "battery_level"
    _attr_native_unit_of_measurement = "%"
    _device_key = "batteryLevel"


class ObiIsOnlineSensor(ObiDeviceValueSensorBase):
    """Sensor for current online state."""

    _attr_unique_id = "obi_is_online"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_translation_key = "is_online"
    _attr_options = ["online", "offline"]
    _device_key = "isOnline"

    @property
    def native_value(self) -> str | None:
        """Return the online status as enum value."""
        value = super().native_value
        if value is None:
            return None
        return "online" if bool(value) else "offline"


class ObiConnectionStrengthSensor(ObiDeviceValueSensorBase):
    """Sensor for connection strength reported by API."""

    _attr_unique_id = "obi_connection_strength"
    _attr_translation_key = "connection_strength"
    _device_key = "connectionStrength"


class ObiLastRecordReceivedAtSensor(ObiDeviceValueSensorBase):
    """Sensor for timestamp of the last received record."""

    _attr_unique_id = "obi_last_record_received_at"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_translation_key = "last_record_received_at"
    _device_key = "lastRecordReceivedAt"

    @property
    def native_value(self) -> datetime | None:
        """Return parsed timestamp value."""
        value = super().native_value
        if not isinstance(value, str):
            return None

        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
