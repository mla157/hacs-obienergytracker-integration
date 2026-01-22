"""The obienergytracker integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import ObiEnergyTrackerAPI
from .const import CONF_BRIDGE_ID, CONF_COUNTRY, CONF_DEVICE_ID, DOMAIN
from .coordinator import ObiEnergyTrackerCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]


type ObiEnergyTrackerConfigEntry = ConfigEntry[ObiEnergyTrackerCoordinator]


async def async_setup_entry(
    hass: HomeAssistant, entry: ObiEnergyTrackerConfigEntry
) -> bool:
    """Set up obienergytracker from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    # Create API client
    session = async_get_clientsession(hass)
    api = ObiEnergyTrackerAPI(
        session=session,
        email=entry.data[CONF_EMAIL],
        password=entry.data[CONF_PASSWORD],
        country=entry.data.get(CONF_COUNTRY, "DE"),
        bridge_id=entry.data.get(CONF_BRIDGE_ID),
        device_id=entry.data.get(CONF_DEVICE_ID),
    )

    # Authenticate
    if not await api.async_login():
        _LOGGER.error("Failed to authenticate with Obi EnergyTracker")
        return False

    # Create coordinator
    coordinator = ObiEnergyTrackerCoordinator(hass, api, entry)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator

    # Forward entry setup to platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: ObiEnergyTrackerConfigEntry
) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id, None)

    return unload_ok
