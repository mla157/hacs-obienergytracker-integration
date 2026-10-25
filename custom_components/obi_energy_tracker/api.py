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

# Identify ourselves honestly as a Home Assistant integration rather than
# impersonating the heyOBI mobile application.
HA_USER_AGENT = "HomeAssistant-ObiEnergyTracker-Integration"

# The meter window only needs to cover the gap since the last poll.  The
# devices upload roughly every 5 minutes, so a 15-minute window is enough to
# always catch the latest reading without requesting hours of data we discard.
METER_WINDOW = timedelta(minutes=15)

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
        user_id: str | None = None,
    ) -> None:
        """Initialize the API client."""
        self.session = session
        self.token_provider = token_provider
        self.bridge_id = bridge_id
        self.device_id = device_id
        self.user_id = user_id
        self.last_token: str | None = None

    async def async_get_token(self) -> str:
        """Obtain a valid access token from the token provider."""
        self.last_token = await self.token_provider()
        return self.last_token

    async def async_get_bridge_info(self) -> dict[str, Any] | None:
        """Get bridge/device IDs and current device details from user profile."""
        try:
            token = await self.async_get_token()
            if not token:
                _LOGGER.error("No access token available")
                return None

            user_id = self.user_id or extract_account_id(token)
            if not user_id:
                _LOGGER.error("No accountId found in token claims")
                return None
            self.user_id = user_id

            url = f"{ENERGY_TRACKING_URL}/users/{user_id}"
            headers = {
                "Accept": "application/vnd.obi.companion.energy-tracking.user.v1+json",
                "Accept-Encoding": "gzip",
                "User-Agent": HA_USER_AGENT,
                "Authorization": f"Bearer {token}",
                "Connection": "Keep-Alive",
            }

            async with self.session.get(url, headers=headers) as response:
                if response.status != 200:
                    _LOGGER.error("Failed to get user info: %d", response.status)
                    return None

                data = await response.json()
                bridge = data.get("bridge")
                if not bridge:
                    _LOGGER.error("No bridge found in user info")
                    return None

                self.bridge_id = bridge.get("id")
                sensors = bridge.get("sensors", [])
                selected_sensor: dict[str, Any] | None = None

                if self.device_id:
                    selected_sensor = next(
                        (
                            sensor
                            for sensor in sensors
                            if isinstance(sensor, dict)
                            and sensor.get("id") == self.device_id
                        ),
                        None,
                    )

                if selected_sensor is None and sensors:
                    first_sensor = sensors[0]
                    selected_sensor = (
                        first_sensor if isinstance(first_sensor, dict) else None
                    )

                if selected_sensor:
                    self.device_id = selected_sensor.get("id")

                if not self.bridge_id or not self.device_id:
                    _LOGGER.error("Could not find bridge_id or device_id")
                    return None

                return {
                    "bridge_id": self.bridge_id,
                    "device_id": self.device_id,
                    "batteryLevel": selected_sensor.get("batteryLevel")
                    if selected_sensor
                    else None,
                    "isOnline": selected_sensor.get("isOnline")
                    if selected_sensor
                    else None,
                    "connectionStrength": selected_sensor.get("connectionStrength")
                    if selected_sensor
                    else None,
                    "lastRecordReceivedAt": selected_sensor.get("lastRecordReceivedAt")
                    if selected_sensor
                    else None,
                }
        except (OSError, ClientError) as err:
            _LOGGER.error("Error getting bridge info: %s", err)
            return None

    async def async_get_device_info(self) -> dict[str, Any] | None:
        """Get current device details from the bridge info response."""
        bridge_info = await self.async_get_bridge_info()
        if not bridge_info:
            return None

        return {
            "batteryLevel": bridge_info.get("batteryLevel"),
            "isOnline": bridge_info.get("isOnline"),
            "connectionStrength": bridge_info.get("connectionStrength"),
            "lastRecordReceivedAt": bridge_info.get("lastRecordReceivedAt"),
        }

    async def async_get_meter_data(self) -> dict[str, Any] | None:
        """Get meter reading data (Zählerstand).

        Uses a short window (default 15 minutes) that matches the device's
        upload rate, instead of fetching hours of historical data.
        """
        try:
            token = await self.async_get_token()
            if not token or not self.bridge_id or not self.device_id:
                return None

            now = datetime.now(timezone.utc)
            start_time = now - METER_WINDOW
            start_time_str = start_time.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
            window_minutes = int(METER_WINDOW.total_seconds() // 60)
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

    def _get_auth_headers(self, token: str) -> dict[str, str]:
        """Get headers with authorization token."""
        accept_header = (
            "application/vnd.obi.companion.energy-tracking.historical-record.v1+json"
        )
        return {
            "Accept": accept_header,
            "Accept-Encoding": "gzip",
            "User-Agent": HA_USER_AGENT,
            "Authorization": f"Bearer {token}",
            "Connection": "Keep-Alive",
        }

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
