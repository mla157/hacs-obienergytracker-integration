"""API client for Obi EnergyTracker."""

from __future__ import annotations

import base64
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
import json
import logging
from typing import Any, TypeAlias

from aiohttp import ClientError, ClientSession

_LOGGER = logging.getLogger(__name__)

# API endpoints
ENERGY_TRACKING_URL = "https://energy-tracking-backend.prod-eks.dbs.obi.solutions"

# Live mode runs on the newer gateway, where the energy-tracking API sits
# behind a path prefix. The historical endpoints above are unaffected.
LIVE_API_BASE = "https://api.obi.com/energytracker/api"
LIVE_WS_URL = "wss://api.obi.com/energytracker/api-livemode/retrieving"
SENSOR_MEDIA_TYPE = "application/vnd.obi.companion.energy-tracking.sensor.v2+json"

FORECAST_MEDIA_TYPE = (
    "application/vnd.obi.companion.energy-tracking.analytics-forecast.v1+json"
)
STANDBY_MEDIA_TYPE = (
    "application/vnd.obi.companion.energy-tracking.analytics-standby.v1+json"
)

# Identify ourselves honestly as a Home Assistant integration rather than
# impersonating the heyOBI mobile application.
HA_USER_AGENT = "HomeAssistant-ObiEnergyTracker-Integration"

# The meter window only needs to cover the gap since the last poll. The
# devices upload roughly every 5 minutes, so a 15-minute window is enough to
# always catch the latest reading without requesting hours of data we discard.
METER_WINDOW = timedelta(minutes=15)

# Fields carried per sensor in the user response. All of them come from the
# one call the integration already makes, so reading more of them costs no
# extra request.
SENSOR_DETAIL_FIELDS = (
    "batteryLevel",
    "isOnline",
    "connectionStrength",
    "lastRecordReceivedAt",
    "firmwareVersion",
    "hardwareVersion",
    "otaStatus",
    "otaProgress",
    "uploadInterval",
)

# The intervals the backend serves standby power for.
STANDBY_INTERVALS = ("daily", "weekly", "monthly", "yearly")

# Lookback window for standby requests. 35 days reliably covers the last
# completed month, which is the longest period the monthly interval needs.
STANDBY_DURATION = "P35D"

TokenProvider: TypeAlias = Callable[[], Awaitable[str]]


def extract_jwt_claims(token: str) -> dict[str, Any]:
    """Extract claims dictionary from a JWT token without external dependencies."""
    parts = token.split(".")
    if len(parts) < 2:
        return {}
    payload = parts[1] + "=" * (-len(parts[1]) % 4)
    try:
        claims = json.loads(base64.urlsafe_b64decode(payload))
    except (ValueError, TypeError):
        return {}
    return claims if isinstance(claims, dict) else {}


def extract_account_id(access_token: str) -> str | None:
    """Extract accountId claim from a JWT access token without external dependencies."""
    claims = extract_jwt_claims(access_token)
    account_id = claims.get("accountId") or claims.get("sub")
    return str(account_id) if account_id is not None else None


class ObiEnergyTrackerAPI:
    """API client for Obi EnergyTracker using OAuth2 Bearer token authentication."""

    def __init__(
        self,
        session: ClientSession,
        token_provider: TokenProvider,
        bridge_id: str | None = None,
        device_id: str | None = None,
        country: str = "DE",
    ) -> None:
        """Initialize the API client."""
        self.session = session
        self._token_provider = token_provider
        self.bridge_id = bridge_id
        self.device_id = device_id
        self.country = country
        self.last_token: str | None = None

    async def async_get_token(self) -> str | None:
        """Obtain a valid access token via the provider callback."""
        try:
            self.last_token = await self._token_provider()
            return self.last_token
        except Exception as err:
            _LOGGER.error("Failed to retrieve access token: %s", err)
            return None

    async def async_get_bridge_info(self) -> dict[str, Any] | None:
        """Get bridge and device IDs, plus current device details."""
        try:
            token = await self.async_get_token()
            if not token:
                return None

            account_id = extract_account_id(token)
            if not account_id:
                _LOGGER.error("Could not extract account_id from token")
                return None

            url = f"{ENERGY_TRACKING_URL}/users/{account_id}"
            headers = {
                "Accept": "application/vnd.obi.companion.energy-tracking.user.v1+json",
                "Accept-Encoding": "gzip",
                "User-Agent": HA_USER_AGENT,
                "Authorization": f"Bearer {token}",
                "Connection": "Keep-Alive",
            }

            async with self.session.get(url, headers=headers) as response:
                if response.status != 200:
                    _LOGGER.error("Failed to get bridge info: %d", response.status)
                    return None

                data = await response.json()
                bridges = data.get("bridges", [])
                if not bridges and isinstance(data.get("bridge"), dict):
                    bridges = [data["bridge"]]

                if not bridges:
                    _LOGGER.error("No bridges found in user data")
                    return None

                bridge = bridges[0]
                self.bridge_id = bridge.get("id")

                sensors = bridge.get("sensors", [])
                selected_sensor = None

                if self.device_id:
                    selected_sensor = next(
                        (s for s in sensors if s.get("id") == self.device_id), None
                    )

                if not selected_sensor and sensors:
                    selected_sensor = sensors[0]

                if selected_sensor:
                    self.device_id = selected_sensor.get("id")

                if not self.bridge_id or not self.device_id:
                    _LOGGER.error("Could not find bridge_id or device_id")
                    return None

                sensor = selected_sensor or {}

                return {
                    "bridge_id": self.bridge_id,
                    "device_id": self.device_id,
                    "bridge_firmware_version": bridge.get("firmwareVersion"),
                    "bridge_hardware_version": bridge.get("hardwareVersion"),
                    **{key: sensor.get(key) for key in SENSOR_DETAIL_FIELDS},
                }
        except (OSError, ClientError) as err:
            _LOGGER.error("Error getting bridge info: %s", err)
            return None

    async def async_get_device_info(self) -> dict[str, Any] | None:
        """Get current device details from the bridge info response."""
        bridge_info = await self.async_get_bridge_info()
        if not bridge_info:
            return None

        return {key: bridge_info.get(key) for key in SENSOR_DETAIL_FIELDS}

    async def async_get_meter_data(
        self, window: timedelta | None = None
    ) -> dict[str, Any] | None:
        """Get meter reading data (Zählerstand).

        Uses a short window (default 15 minutes) that matches the device's
        upload rate, instead of fetching hours of historical data.
        """
        try:
            token = await self.async_get_token()
            if not token or not self.bridge_id or not self.device_id:
                return None

            target_window = window or METER_WINDOW
            now = datetime.now(timezone.utc)
            start_time = now - target_window
            start_time_str = start_time.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
            window_minutes = int(target_window.total_seconds() // 60)
            duration_str = f"{start_time_str}/PT{window_minutes}M"

            url = (
                f"{ENERGY_TRACKING_URL}/historical-data/"
                f"{self.bridge_id}/{self.device_id}/meter"
            )

            params = {
                "duration": duration_str,
                "measures": "energy,negative_energy",
            }

            headers = self._get_auth_headers(token)

            async with self.session.get(
                url, params=params, headers=headers
            ) as response:
                if response.status == 200:
                    return await response.json()
                _LOGGER.error("Failed to get meter data: %d", response.status)
                return None
        except (OSError, ClientError) as err:
            _LOGGER.error("Error getting meter data: %s", err)
            return None

    async def async_get_consumption_forecast(self) -> dict[str, Any] | None:
        """Get the weekly and monthly consumption forecast.

        The response carries consumptionForecastWeekly and
        consumptionForecastMonthly, both in watt-hours.
        """
        token = await self.async_get_token()
        if not token or not self.bridge_id or not self.device_id:
            return None

        url = (
            f"{ENERGY_TRACKING_URL}/analytics/"
            f"{self.bridge_id}/{self.device_id}/forecast"
        )
        headers = self._get_auth_headers(token, accept=FORECAST_MEDIA_TYPE)

        try:
            async with self.session.get(url, headers=headers) as response:
                if response.status != 200:
                    _LOGGER.debug(
                        "Failed to get consumption forecast: %d", response.status
                    )
                    return None

                data = await response.json()
                if not isinstance(data, dict):
                    _LOGGER.debug(
                        "Unexpected forecast response type: %s", type(data).__name__
                    )
                    return None
                return data
        except (OSError, ClientError) as err:
            _LOGGER.debug("Error getting consumption forecast: %s", err)
            return None

    async def async_get_standby_power(
        self, interval: str
    ) -> list[dict[str, Any]] | None:
        """Get average standby power records for one completed-period interval.

        Despite the "standby consumption" wording the app uses, the API
        returns a power value in watts, not an energy total.
        """
        token = await self.async_get_token()
        if not token or not self.bridge_id or not self.device_id:
            return None

        url = (
            f"{ENERGY_TRACKING_URL}/analytics/"
            f"{self.bridge_id}/{self.device_id}/{interval}/standby"
        )

        # The window has to be sent as an ISO 8601 interval; the backend
        # rejects a bare duration.
        start = datetime.now(timezone.utc) - timedelta(days=35)
        start_str = start.strftime("%Y-%m-%dT%H:%M:%S.000Z")
        params = {"duration": f"{start_str}/{STANDBY_DURATION}"}
        headers = self._get_auth_headers(token, accept=STANDBY_MEDIA_TYPE)

        try:
            async with self.session.get(
                url, params=params, headers=headers
            ) as response:
                if response.status != 200:
                    _LOGGER.debug(
                        "Failed to get %s standby power: %d", interval, response.status
                    )
                    return None

                data = await response.json()
                if not isinstance(data, list):
                    _LOGGER.debug(
                        "Unexpected %s standby response type: %s",
                        interval,
                        type(data).__name__,
                    )
                    return None
                return data
        except (OSError, ClientError) as err:
            _LOGGER.debug("Error getting %s standby power: %s", interval, err)
            return None

    def _get_auth_headers(self, token: str, accept: str | None = None) -> dict[str, str]:
        """Get headers with authorization token."""
        accept_header = accept or (
            "application/vnd.obi.companion.energy-tracking.historical-record.v1+json"
        )
        return {
            "Accept": accept_header,
            "Accept-Encoding": "gzip",
            "User-Agent": HA_USER_AGENT,
            "Authorization": f"Bearer {token}",
            "Connection": "Keep-Alive",
        }

    async def async_get_energy_consumer(
        self, device_id: str | None = None
    ) -> dict[str, Any] | None:
        """Get energy consumer pricing and tariff info (kwh_price, feed_in_compensation)."""
        target_id = device_id or self.device_id
        if not target_id:
            return None

        try:
            token = await self.async_get_token()
            if not token:
                return None

            url = f"{ENERGY_TRACKING_URL}/energy-consumers/{target_id}"
            headers = {
                "Accept": "application/vnd.obi.companion.energy-tracking.energy-consumer.v1+json",
                "Accept-Encoding": "gzip",
                "User-Agent": HA_USER_AGENT,
                "Authorization": f"Bearer {token}",
                "Connection": "Keep-Alive",
            }

            async with self.session.get(url, headers=headers) as response:
                if response.status == 200:
                    return await response.json()
                return None
        except (OSError, ClientError) as err:
            _LOGGER.debug("Error getting energy consumer for %s: %s", target_id, err)
            return None

    async def async_get_bridge_firmware_update(
        self, bridge_id: str | None = None
    ) -> dict[str, Any] | None:
        """Check for pending firmware updates for the bridge."""
        target_bridge = bridge_id or self.bridge_id
        if not target_bridge:
            return None

        try:
            token = await self.async_get_token()
            if not token:
                return None

            url = f"{ENERGY_TRACKING_URL}/bridges/{target_bridge}/firmware-update"
            headers = {
                "Accept": "application/vnd.obi.companion.energy-tracking.firmware-update.v1+json",
                "Accept-Encoding": "gzip",
                "User-Agent": HA_USER_AGENT,
                "Authorization": f"Bearer {token}",
                "Connection": "Keep-Alive",
            }

            async with self.session.get(url, headers=headers) as response:
                if response.status == 200:
                    return await response.json()
                return None
        except (OSError, ClientError) as err:
            _LOGGER.debug("Error checking firmware update for %s: %s", target_bridge, err)
            return None

    async def async_trigger_bridge_firmware_update(
        self, firmware_id: str, bridge_id: str | None = None
    ) -> bool:
        """Trigger an over-the-air firmware update for the bridge."""
        target_bridge = bridge_id or self.bridge_id
        if not target_bridge or not firmware_id:
            return False

        try:
            token = await self.async_get_token()
            if not token:
                return False

            url = f"{ENERGY_TRACKING_URL}/bridges/{target_bridge}/firmware-update/{firmware_id}"
            headers = {
                "Accept": "application/vnd.obi.companion.energy-tracking.firmware-update.v1+json",
                "Accept-Encoding": "gzip",
                "User-Agent": HA_USER_AGENT,
                "Authorization": f"Bearer {token}",
                "Connection": "Keep-Alive",
            }

            async with self.session.post(url, headers=headers) as response:
                return response.status in (200, 202, 204)
        except (OSError, ClientError) as err:
            _LOGGER.error("Error triggering firmware update: %s", err)
            return False

    async def async_set_upload_interval(self, interval: int) -> bool:
        """Set the sensor's upload interval, which is what drives live mode.

        The backend accepts only the two values the app uses (2 seconds for
        live, 300 for idle) and answers 400 for anything else.
        """
        try:
            token = await self.async_get_token()
            if not token or not self.device_id:
                return False

            url = f"{LIVE_API_BASE}/sensors/{self.device_id}"
            payload = json.dumps({"id": self.device_id, "uploadInterval": interval})
            headers = {
                "Accept": SENSOR_MEDIA_TYPE,
                "Content-Type": SENSOR_MEDIA_TYPE,
                "Accept-Encoding": "gzip",
                "User-Agent": HA_USER_AGENT,
                "Authorization": f"Bearer {token}",
                "Connection": "Keep-Alive",
            }

            async with self.session.patch(
                url, data=payload, headers=headers
            ) as response:
                if response.status >= 300:
                    _LOGGER.error(
                        "Failed to set upload interval to %d: %d %s",
                        interval,
                        response.status,
                        (await response.text())[:200],
                    )
                    return False
                return True
        except (OSError, ClientError) as err:
            _LOGGER.error("Error setting upload interval: %s", err)
            return False

    def live_ws_connect(self, token: str | None = None) -> Any:
        """Return the websocket connection for live readings.

        Must be wss: the backend answers plain ws on port 80 with HTTP 400.
        """
        auth_token = token or self.last_token or ""
        return self.session.ws_connect(
            LIVE_WS_URL,
            params={
                "bridgeId": self.bridge_id or "",
                "sensorId": self.device_id or "",
            },
            headers={
                "Authorization": f"Bearer {auth_token}",
                "User-Agent": HA_USER_AGENT,
            },
            heartbeat=30,
        )
