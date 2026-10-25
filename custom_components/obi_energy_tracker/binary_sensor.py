"""Binary sensor platform for Obi EnergyTracker."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import ObiEnergyTrackerConfigEntry
from .const import DOMAIN
from .coordinator import ObiEnergyTrackerCoordinator

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ObiEnergyTrackerConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up binary sensors from a config entry."""
    coordinator = config_entry.runtime_data
    async_add_entities([ObiIsOnlineBinarySensor(coordinator)])


class ObiIsOnlineBinarySensor(CoordinatorEntity[ObiEnergyTrackerCoordinator], BinarySensorEntity):
    """Connectivity binary sensor indicating if the tracker is online."""

    _attr_has_entity_name = True
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "is_online"

    def __init__(self, coordinator: ObiEnergyTrackerCoordinator) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator)
        device_id = coordinator.api.device_id or "sensor"
        bridge_id = coordinator.api.bridge_id
        self._attr_unique_id = f"obi_{device_id}_is_online"

        device_info: dict[str, Any] = {
            "identifiers": {(DOMAIN, device_id)},
            "name": "OBI Energy Tracker Sensor",
            "manufacturer": "OBI",
            "model": "Energy Tracker Sensor",
        }
        if bridge_id:
            device_info["via_device"] = (DOMAIN, bridge_id)
        self._attr_device_info = device_info

    @property
    def is_on(self) -> bool | None:
        """Return true if the device is online."""
        if not self.coordinator.data:
            return None
        device = self.coordinator.data.get("device")
        if isinstance(device, dict):
            return device.get("isOnline")
        return None

