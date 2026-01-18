"""Diagnostics support for Obi EnergyTracker."""

from __future__ import annotations

import logging
from typing import Any

from aiohttp import ClientError

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from . import ObiEnergyTrackerConfigEntry
from .api import ObiEnergyTrackerAPI
from .const import CONF_BRIDGE_ID, CONF_COUNTRY, CONF_DEVICE_ID

_LOGGER = logging.getLogger(__name__)


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, config_entry: ObiEnergyTrackerConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    # Create API client to test connection
    session = async_get_clientsession(hass)
    api = ObiEnergyTrackerAPI(
        session=session,
        email=config_entry.data.get("email", ""),
        password=config_entry.data.get("password", ""),
        country=config_entry.data.get(CONF_COUNTRY, "DE"),
        bridge_id=config_entry.data.get(CONF_BRIDGE_ID),
        device_id=config_entry.data.get(CONF_DEVICE_ID),
    )

    api_available = False
    try:
        api_available = await api.async_login()
    except (OSError, ClientError) as err:
        _LOGGER.debug("Diagnostics login failed: %s", err)
        api_available = False

    return {
        "config_entry_data": {
            "email": config_entry.data.get("email", ""),
            "country": config_entry.data.get(CONF_COUNTRY, "DE"),
            "bridge_id": config_entry.data.get(CONF_BRIDGE_ID),
            "device_id": config_entry.data.get(CONF_DEVICE_ID),
        },
        "api_available": api_available,
    }
