"""Update platform for Obi EnergyTracker bridge firmware."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.update import (
    UpdateDeviceClass,
    UpdateEntity,
    UpdateEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import ObiEnergyTrackerConfigEntry
from .const import DOMAIN
from .coordinator import ObiEnergyTrackerCoordinator

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ObiEnergyTrackerConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up update entities from a config entry."""
    coordinator = config_entry.runtime_data
    if coordinator.api.bridge_id:
        async_add_entities([ObiBridgeUpdateEntity(coordinator)])


class ObiBridgeUpdateEntity(CoordinatorEntity[ObiEnergyTrackerCoordinator], UpdateEntity):
    """Firmware update entity for the OBI Energy Tracker Bridge."""

    _attr_has_entity_name = True
    _attr_device_class = UpdateDeviceClass.FIRMWARE
    _attr_supported_features = (
        UpdateEntityFeature.INSTALL | UpdateEntityFeature.PROGRESS
    )

    def __init__(self, coordinator: ObiEnergyTrackerCoordinator) -> None:
        """Initialize the update entity."""
        super().__init__(coordinator)
        bridge_id = coordinator.api.bridge_id or "bridge"
        self._attr_unique_id = f"obi_bridge_{bridge_id}_firmware"
        self._attr_translation_key = "firmware"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, bridge_id)},
            "name": "OBI Energy Tracker Bridge",
            "manufacturer": "OBI",
            "model": "Energy Tracker Bridge",
        }

    @property
    def installed_version(self) -> str | None:
        """Return currently installed bridge firmware version."""
        if not self.coordinator.data:
            return None
        device = self.coordinator.data.get("device")
        if isinstance(device, dict):
            return device.get("firmwareVersion")
        return None

    @property
    def latest_version(self) -> str | None:
        """Return the latest available firmware version."""
        firmware = (self.coordinator.data or {}).get("firmware")
        if isinstance(firmware, dict):
            return firmware.get("version") or self.installed_version
        return self.installed_version

    @property
    def release_summary(self) -> str | None:
        """Return release notes or changelog."""
        firmware = (self.coordinator.data or {}).get("firmware")
        if isinstance(firmware, dict):
            return firmware.get("changeLog") or firmware.get("releaseNotes")
        return None

    @property
    def in_progress(self) -> bool:
        """Return if an update is currently in progress."""
        firmware = (self.coordinator.data or {}).get("firmware")
        if isinstance(firmware, dict):
            status = str(firmware.get("status", "")).lower()
            return status in ("downloading", "installing", "updating", "started")
        return False

    async def async_install(self, version: str | None, backup: bool, **kwargs: Any) -> None:
        """Install an available firmware update."""
        firmware = (self.coordinator.data or {}).get("firmware")
        if not isinstance(firmware, dict) or "id" not in firmware:
            _LOGGER.warning("No firmware update available to install")
            return

        firmware_id = str(firmware["id"])
        _LOGGER.info("Starting firmware update to version %s (id: %s)", version, firmware_id)
        success = await self.coordinator.api.async_trigger_bridge_firmware_update(firmware_id)
        if success:
            await self.coordinator.async_request_refresh()
        else:
            _LOGGER.error("Failed to trigger firmware update")

