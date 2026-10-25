"""Diagnostics support for Obi EnergyTracker."""

from __future__ import annotations

import logging
from typing import Any

from aiohttp import ClientError

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_entry_oauth2_flow
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from . import ObiEnergyTrackerConfigEntry
from .api import ObiEnergyTrackerAPI
from .const import CONF_BRIDGE_ID, CONF_DEVICE_ID
from .oauth2 import oauth_token_provider

_LOGGER = logging.getLogger(__name__)

TO_REDACT = {"token", "refresh_token", "access_token"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, config_entry: ObiEnergyTrackerConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    api_available = False

    if "token" in config_entry.data:
        try:
            implementation = (
                await config_entry_oauth2_flow.async_get_config_entry_implementation(
                    hass, config_entry
                )
            )
            oauth_session = config_entry_oauth2_flow.OAuth2Session(
                hass, config_entry, implementation
            )
            api = ObiEnergyTrackerAPI(
                session=async_get_clientsession(hass),
                token_provider=oauth_token_provider(oauth_session),
                bridge_id=config_entry.data.get(CONF_BRIDGE_ID),
                device_id=config_entry.data.get(CONF_DEVICE_ID),
            )
            info = await api.async_get_bridge_info()
            api_available = info is not None
        except (OSError, ClientError) as err:
            _LOGGER.debug("Diagnostics API test failed: %s", err)
            api_available = False

    return {
        "config_entry_data": async_redact_data(dict(config_entry.data), TO_REDACT),
        "api_available": api_available,
        "coordinator_data": (
            config_entry.runtime_data.data
            if hasattr(config_entry, "runtime_data") and config_entry.runtime_data
            else None
        ),
    }
