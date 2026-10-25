"""The obienergytracker integration."""

from __future__ import annotations

import logging
from typing import TypeAlias

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import config_entry_oauth2_flow
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import ObiEnergyTrackerAPI
from .const import CONF_BRIDGE_ID, CONF_DEVICE_ID, DOMAIN
from .coordinator import ObiEnergyTrackerCoordinator
from .oauth2 import KeycloakOAuth2Implementation, oauth_token_provider

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.BINARY_SENSOR,
    Platform.UPDATE,
]

ObiEnergyTrackerConfigEntry: TypeAlias = ConfigEntry[ObiEnergyTrackerCoordinator]


async def async_setup_entry(
    hass: HomeAssistant, entry: ObiEnergyTrackerConfigEntry
) -> bool:
    """Set up obienergytracker from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    # Register OAuth2 implementation
    config_entry_oauth2_flow.async_register_implementation(
        hass, DOMAIN, KeycloakOAuth2Implementation(hass)
    )

    # Migrate legacy username/password entries if token is missing
    if "token" not in entry.data:
        entry.async_start_reauth(hass)
        raise ConfigEntryAuthFailed(
            "OBI Energy Tracker now uses OAuth2 authentication. Please re-authenticate."
        )

    implementation = (
        await config_entry_oauth2_flow.async_get_config_entry_implementation(
            hass, entry
        )
    )
    oauth_session = config_entry_oauth2_flow.OAuth2Session(hass, entry, implementation)

    # Standard HA shared ClientSession works cleanly with OAuth2 endpoints
    session = async_get_clientsession(hass)
    token_provider = oauth_token_provider(oauth_session)

    api = ObiEnergyTrackerAPI(
        session=session,
        token_provider=token_provider,
        bridge_id=entry.data.get(CONF_BRIDGE_ID),
        device_id=entry.data.get(CONF_DEVICE_ID),
    )

    # Create coordinator and perform first refresh
    coordinator = ObiEnergyTrackerCoordinator(hass, api, entry)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator

    # Register Bridge gateway device in HA device registry
    if api.bridge_id:
        device_reg = dr.async_get(hass)
        device_info = coordinator.data.get("device") or {}
        device_reg.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={(DOMAIN, api.bridge_id)},
            name="OBI Energy Tracker Bridge",
            manufacturer="OBI",
            model="Energy Tracker Bridge",
            sw_version=device_info.get("firmwareVersion"),
            hw_version=device_info.get("hardwareVersion"),
        )

    # Launch background import of historical statistics for HA Energy Dashboard
    entry.async_create_background_task(
        hass, coordinator.async_import_history(), f"{DOMAIN}_import_history"
    )

    # Forward entry setup to platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: ObiEnergyTrackerConfigEntry
) -> bool:
    """Unload a config entry."""
    # Switch live mode off first: it has to put the sensor's upload interval
    # back to its idle value, otherwise the battery keeps draining at the
    # two-second rate after the entry is gone.
    if hasattr(entry, "runtime_data") and entry.runtime_data:
        await entry.runtime_data.live.async_turn_off()

    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id, None)

    return unload_ok
