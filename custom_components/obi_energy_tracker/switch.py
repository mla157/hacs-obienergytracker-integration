"""Switch platform for Obi EnergyTracker live mode."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import ObiEnergyTrackerConfigEntry
from .const import DOMAIN
from .coordinator import ObiEnergyTrackerCoordinator
from .live import ObiLiveMode

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ObiEnergyTrackerConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the live mode switch."""
    coordinator = config_entry.runtime_data
    async_add_entities([ObiLiveModeSwitch(coordinator)])


class ObiLiveModeSwitch(SwitchEntity):
    """Switch that puts the sensor into its two-second upload interval."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_unique_id = "obi_live_mode"
    _attr_translation_key = "live_mode"
    _attr_icon = "mdi:access-point"

    def __init__(self, coordinator: ObiEnergyTrackerCoordinator) -> None:
        """Initialize the switch."""
        self._live = coordinator.live
        device_id = coordinator.api.device_id or "sensor"
        bridge_id = coordinator.api.bridge_id
        device_info: dict[str, Any] = {
            "identifiers": {(DOMAIN, device_id)},
            "name": "OBI Energy Tracker Sensor",
            "manufacturer": "OBI",
            "model": "Energy Tracker Sensor",
        }
        if bridge_id:
            device_info["via_device"] = (DOMAIN, bridge_id)
        self._attr_device_info = device_info

    async def async_added_to_hass(self) -> None:
        """Subscribe to live mode updates."""
        self.async_on_remove(self._live.async_add_listener(self._handle_update))

    @callback
    def _handle_update(self) -> None:
        """Write the new state when live mode reports a change."""
        self.async_write_ha_state()

    @property
    def is_on(self) -> bool:
        """Return whether live mode is switched on."""
        return self._live.is_on

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose connection state so failures are visible in the UI."""
        return {
            "connected": self._live.connected,
            "timeout_seconds": self._live.timeout,
            "last_error": self._live.last_error,
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Switch live mode on."""
        await self._live.async_turn_on()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Switch live mode off."""
        await self._live.async_turn_off()
