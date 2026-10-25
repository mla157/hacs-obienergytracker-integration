"""OAuth2 support for Obi EnergyTracker integration."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
import logging
from typing import TypeAlias

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.config_entry_oauth2_flow import (
    LocalOAuth2ImplementationWithPkce,
    OAuth2Session,
)

from .const import (
    DOMAIN,
    OAUTH2_AUTHORIZE_URL,
    OAUTH2_CLIENT_ID,
    OAUTH2_LOGOUT_URL,
    OAUTH2_TOKEN_URL,
)

_LOGGER = logging.getLogger(__name__)

TokenProvider: TypeAlias = Callable[[], Awaitable[str]]


def oauth_token_provider(oauth_session: OAuth2Session) -> TokenProvider:
    """Return an async callable that guarantees a valid access token."""
    async def _async_token() -> str:
        await oauth_session.async_ensure_token_valid()
        token: str = oauth_session.token["access_token"]
        return token

    return _async_token


async def async_revoke_session(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Revoke the current session in Keycloak."""
    refresh_token = (entry.data.get("token") or {}).get("refresh_token")
    if not refresh_token:
        _LOGGER.debug("No refresh token to revoke, skipping Keycloak logout")
        return

    try:
        async with async_get_clientsession(hass).post(
            OAUTH2_LOGOUT_URL,
            data={"client_id": OAUTH2_CLIENT_ID, "refresh_token": refresh_token},
        ) as resp:
            if resp.status not in (200, 204):
                _LOGGER.warning(
                    "Keycloak logout returned %s: %s", resp.status, await resp.text()
                )
    except aiohttp.ClientError as err:
        _LOGGER.warning("Keycloak logout failed: %s", err)


class KeycloakOAuth2Implementation(LocalOAuth2ImplementationWithPkce):
    """Local OAuth2 implementation using PKCE for Obi Keycloak authentication."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the Keycloak OAuth2 implementation."""
        super().__init__(
            hass,
            domain=DOMAIN,
            client_id=OAUTH2_CLIENT_ID,
            authorize_url=OAUTH2_AUTHORIZE_URL,
            token_url=OAUTH2_TOKEN_URL,
        )
