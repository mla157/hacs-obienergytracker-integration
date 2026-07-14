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
        ObiFeedInMeterReadingSensor(coordinator),
        ObiBatteryLevelSensor(coordinator),
        ObiIsOnlineSensor(coordinator),
        ObiConnectionStrengthSensor(coordinator),
        ObiLastRecordReceivedAtSensor(coordinator),
    ]

    async_add_entities(sensors)


def _extract_meter_reading(meter_data: Any, measure: str) -> float | None:
    """Extract the latest reading for a given measure from meter data.

    The meter endpoint can return either a single record (dict) or a list of
    records, each optionally tagged with a "measure" (e.g. "energy" or
    "negative_energy"). Falls back to legacy shapes ("energy"/"value" keys
    without a "measure" tag) for the "energy" measure only.
    """
    if not meter_data:
        return None

    records = meter_data if isinstance(meter_data, list) else [meter_data]
    records = [record for record in records if isinstance(record, dict)]
    if not records:
        return None

    matching = [record for record in records if record.get("measure") == measure]
    if matching:
        return matching[-1].get("value")

    if measure == "energy":
        legacy = records[-1]
        if "energy" in legacy:
            return legacy["energy"]
        if "value" in legacy:
            return legacy["value"]

    return None


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


class ObiMeterSensorBase(ObiEnergySensorBase):
    """Base sensor for cumulative meter readings (Zählerstand)."""

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = "Wh"
    _measure: str

    def __init__(self, coordinator: ObiEnergyTrackerCoordinator) -> None:
        """Initialize the meter sensor."""
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
        """Return the meter reading value for this sensor's measure."""
        _LOGGER.debug(
            "%s native_value called. Data: %s",
            type(self).__name__,
            self.coordinator.data,
        )
        if not self.coordinator.data:
            return None

        return _extract_meter_reading(self.coordinator.data.get("meter"), self._measure)


class ObiMeterReadingSensor(ObiMeterSensorBase):
    """Sensor for total meter reading (Zählerstand / Bezug)."""

    _attr_unique_id = "obi_meter_reading"
    _attr_translation_key = "meter_reading"
    _measure = "energy"


class ObiFeedInMeterReadingSensor(ObiMeterSensorBase):
    """Sensor for total feed-in meter reading (Zählerstand Netzeinspeisung)."""

    _attr_unique_id = "obi_feed_in_meter_reading"
    _attr_translation_key = "feed_in_meter_reading"
    _measure = "negative_energy"


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
