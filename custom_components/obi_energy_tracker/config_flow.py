"""Config flow for Obi EnergyTracker integration using OAuth2."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    SOURCE_REAUTH,
    ConfigEntry,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers import config_entry_oauth2_flow

from .api import ObiEnergyTrackerAPI, extract_account_id, extract_jwt_claims
from .const import (
    CONF_BRIDGE_ID,
    CONF_DEVICE_ID,
    CONF_SCOPED_IDS,
    DOMAIN,
    OAUTH2_SCOPES,
)
from .oauth2 import KeycloakOAuth2Implementation, async_revoke_session
from .session import async_create_obi_session

_LOGGER = logging.getLogger(__name__)


class ObiEnergyTrackerConfigFlow(
    config_entry_oauth2_flow.AbstractOAuth2FlowHandler,
    domain=DOMAIN,
):
    """Handle a config flow for Obi EnergyTracker."""

    DOMAIN = DOMAIN
    VERSION = 1
    MINOR_VERSION = 2

    @staticmethod
    @callback
    def async_get_options_flow(entry: ConfigEntry) -> ObiEnergyTrackerOptionsFlow:
        """Return options flow handler."""
        return ObiEnergyTrackerOptionsFlow()

    @property
    def logger(self) -> logging.Logger:
        """Return logger."""
        return _LOGGER

    @property
    def extra_authorize_data(self) -> dict[str, Any]:
        """Extra data that needs to be appended to the authorize url."""
        return {"scope": OAUTH2_SCOPES}

    def _register_implementation(self) -> None:
        """Register the Keycloak OAuth2 implementation."""
        self.async_register_implementation(
            self.hass, KeycloakOAuth2Implementation(self.hass)
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle user initiate step: redirect to Obi Keycloak login."""
        self._register_implementation()
        return await self.async_step_pick_implementation()

    async def async_oauth_create_entry(self, data: dict[str, Any]) -> ConfigFlowResult:
        """Create entry from OAuth2 token response."""
        access_token = data.get("token", {}).get("access_token", "")
        if not access_token:
            return self.async_abort(reason="oauth_error")

        account_id = extract_account_id(access_token)
        reauth_entry = (
            self._get_reauth_entry() if self.source == SOURCE_REAUTH else None
        )

        # Test the connection and discover bridge/device IDs.
        # Use the custom session to avoid the OBI CDN ALPN issue.
        session = async_create_obi_session(self.hass)

        async def _static_token() -> str:
            return access_token

        try:
            api = ObiEnergyTrackerAPI(
                session=session,
                token_provider=_static_token,
                # On reauth stay bound to the entry's own sensor, so an
                # account with several bridges never swaps meters.
                bridge_id=reauth_entry.data.get(CONF_BRIDGE_ID) if reauth_entry else None,
                device_id=reauth_entry.data.get(CONF_DEVICE_ID) if reauth_entry else None,
            )

            if reauth_entry is None:
                sensors = await api.async_list_sensors()
                info = None
            else:
                sensors = None
                info = await api.async_get_bridge_info()
        finally:
            await session.close()

        if reauth_entry is None:
            if sensors is None:
                return self.async_abort(reason="cannot_connect")
            configured = {
                entry.data.get(CONF_DEVICE_ID)
                for entry in self._async_current_entries(include_ignore=False)
            }
            available = [s for s in sensors if s["device_id"] not in configured]
            if not available:
                return self.async_abort(reason="already_configured")
            self._oauth_data = data
            self._available_sensors = available
            if len(available) == 1:
                return await self._async_create_sensor_entry(available[0])
            return await self.async_step_pick_sensor()

        if not info:
            # Sensor of this entry not found: wrong account or OBI unreachable.
            return self.async_abort(reason="wrong_account")

        data[CONF_BRIDGE_ID] = info["bridge_id"]
        data[CONF_DEVICE_ID] = info["device_id"]

        if reauth_entry.data.get(CONF_SCOPED_IDS):
            # Per-sensor entry: unique_id is the sensor ID, which was just
            # verified to belong to the account that logged in.
            data[CONF_SCOPED_IDS] = True
            await self.async_set_unique_id(reauth_entry.unique_id)
            return self.async_update_reload_and_abort(reauth_entry, data=data)

        unique_id = account_id or info["device_id"]

        if reauth_entry is not None:
            is_legacy = (
                "token" not in reauth_entry.data
                or "@" in str(reauth_entry.unique_id)
                or reauth_entry.unique_id == reauth_entry.data.get("email")
            )

            if is_legacy:
                # Compare email if both are present to prevent logging into a completely different account
                id_token = data.get("token", {}).get("id_token", "")
                id_claims = extract_jwt_claims(id_token) if id_token else {}
                access_claims = extract_jwt_claims(access_token)
                token_email = (
                    access_claims.get("email")
                    or id_claims.get("email")
                    or ""
                ).lower()
                legacy_email = (
                    reauth_entry.data.get("email")
                    or reauth_entry.unique_id
                    or ""
                ).lower()

                if token_email and legacy_email and token_email != legacy_email:
                    _LOGGER.warning(
                        "Reauth email mismatch: logged in as '%s', expected '%s'",
                        token_email,
                        legacy_email,
                    )
                    return self.async_abort(reason="wrong_account")

                # Migrate unique_id from email to account_id
                if unique_id:
                    self.hass.config_entries.async_update_entry(
                        reauth_entry, unique_id=unique_id
                    )
                    await self.async_set_unique_id(unique_id)

                new_data = {**reauth_entry.data, **data}
                new_data.pop("password", None)
                new_data.pop("email", None)
                return self.async_update_reload_and_abort(reauth_entry, data=new_data)

            # Standard OAuth2 re-authentication
            if unique_id:
                await self.async_set_unique_id(unique_id)
            if reauth_entry.unique_id is not None and unique_id is None:
                return self.async_abort(reason="wrong_account")
            self._abort_if_unique_id_mismatch(reason="wrong_account")
            return self.async_update_reload_and_abort(reauth_entry, data=data)

        return self.async_abort(reason="oauth_error")

    async def async_step_pick_sensor(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Let the user choose which sensor (bridge) this entry is for."""
        by_id = {s["device_id"]: s for s in self._available_sensors}
        if user_input is not None:
            return await self._async_create_sensor_entry(by_id[user_input["sensor"]])

        def _label(sensor: dict[str, Any]) -> str:
            state = {True: "online", False: "offline"}.get(sensor.get("isOnline"), "?")
            last = str(sensor.get("lastRecordReceivedAt") or "-")[:16].replace("T", " ")
            return (
                f"{sensor.get('name') or 'Sensor'} …{str(sensor['device_id'])[-6:]} "
                f"(Bridge …{str(sensor['bridge_id'])[-6:]}, {state}, {last})"
            )

        return self.async_show_form(
            step_id="pick_sensor",
            data_schema=vol.Schema(
                {
                    vol.Required("sensor"): vol.In(
                        {device_id: _label(s) for device_id, s in by_id.items()}
                    )
                }
            ),
        )

    async def _async_create_sensor_entry(
        self, sensor: dict[str, Any]
    ) -> ConfigFlowResult:
        """Create a per-sensor entry with sensor-scoped unique IDs."""
        await self.async_set_unique_id(sensor["device_id"])
        self._abort_if_unique_id_configured()
        data = {
            **self._oauth_data,
            CONF_BRIDGE_ID: sensor["bridge_id"],
            CONF_DEVICE_ID: sensor["device_id"],
            CONF_SCOPED_IDS: True,
        }
        return self.async_create_entry(
            title=(
                f"OBI Energy Tracker ({sensor.get('name') or '…' + str(sensor['device_id'])[-6:]})"
            ),
            data=data,
        )

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> ConfigFlowResult:
        """Handle reauthorization request."""
        self._register_implementation()
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm reauth dialog."""
        if user_input is None:
            return self.async_show_form(step_id="reauth_confirm")

        return await self.async_step_pick_implementation()


class ObiEnergyTrackerOptionsFlow(OptionsFlow):
    """Handle options flow for Obi EnergyTracker."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Allow user to revoke session and log in again."""
        if user_input is None:
            return self.async_show_form(step_id="init", data_schema=vol.Schema({}))

        await async_revoke_session(self.hass, self.config_entry)
        self.config_entry.async_start_reauth(self.hass)
        return self.async_abort(reason="logged_out")
