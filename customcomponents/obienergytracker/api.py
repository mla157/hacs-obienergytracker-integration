"""API client for Obi EnergyTracker."""

from __future__ import annotations

from datetime import datetime, timedelta
import logging
from typing import Any

from aiohttp import ClientError, ClientSession
import jwt

_LOGGER = logging.getLogger(__name__)

# API endpoints
LOGIN_URL = "https://www.obi.de/regi/auth/api/public/login"
ENERGY_TRACKING_URL = "https://energy-tracking-backend.prod-eks.dbs.obi.solutions"


class ObiEnergyTrackerAPI:
    """API client for Obi EnergyTracker."""

    def __init__(
        self,
        session: ClientSession,
        email: str,
        password: str,
        country: str = "DE",
        bridge_id: str | None = None,
        device_id: str | None = None,
    ) -> None:
        """Initialize the API client."""
        self.session = session
        self.email = email
        self.password = password
        self.country = country
        self.token: str | None = None
        self.bridge_id = bridge_id
        self.device_id = device_id

    async def async_login(self) -> bool:
        """Authenticate with the Obi EnergyTracker API."""
        try:
            payload = {
                "email": self.email,
                "password": self.password,
                "country": self.country,
            }

            headers = {
                "Accept-Encoding": "gzip",
                "Connection": "Keep-Alive",
                "Content-Type": "application/json",
                "x-app-type": "b2c",
                "x-obi-locale": "de-DE",
                "User-Agent": "heyOBI APP / Android Phone 30",
            }

            async with self.session.post(
                LOGIN_URL, json=payload, headers=headers
            ) as response:
                if response.status != 200:
                    _LOGGER.error(
                        "Login failed with status %d",
                        response.status,
                    )
                    return False

                data = await response.json()
                self.token = data.get("token")

                if not self.token:
                    _LOGGER.error("No token received from login response")
                    return False

                _LOGGER.debug("Successfully authenticated with Obi EnergyTracker")
                return True
        except (OSError, ClientError) as err:
            _LOGGER.error("Login error: %s", err)
            return False

    async def async_get_bridge_info(self) -> dict[str, str] | None:
        """Get bridge and device IDs from user profile."""
        if not self.token:
            return None

        try:
            # Decode JWT to get userId
            decoded_token = jwt.decode(self.token, options={"verify_signature": False})
            user_id = decoded_token.get("accountId")

            if not user_id:
                _LOGGER.error("No accountId found in token")
                return None

            url = f"{ENERGY_TRACKING_URL}/users/{user_id}"
            headers = {
                "Accept": "application/vnd.obi.companion.energy-tracking.user.v1+json",
                "Accept-Encoding": "gzip",
                "User-Agent": "app_client",
                "Authorization": f"Bearer {self.token}",
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
                if sensors:
                    self.device_id = sensors[0].get("id")

                if not self.bridge_id or not self.device_id:
                    _LOGGER.error("Could not find bridge_id or device_id")
                    return None

                return {
                    "bridge_id": self.bridge_id,
                    "device_id": self.device_id,
                }
        except (jwt.DecodeError, OSError, ClientError) as err:
            _LOGGER.error("Error getting bridge info: %s", err)
            return None

    async def async_get_totals(self) -> dict[str, Any] | None:
        """Get total energy data (both energy and negative_energy).

        Returns a dict with:
        - energy: total energy produced
        - negative_energy: total energy fed to grid
        """
        if not self.token or not self.bridge_id:
            return None

        try:
            url = f"{ENERGY_TRACKING_URL}/historical-data/{self.bridge_id}/total"
            headers = self._get_auth_headers()

            totals = {}

            # Fetch energy (produced)
            params = {"measures": "energy"}
            async with self.session.get(
                url, params=params, headers=headers
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    _LOGGER.debug("Energy totals response: %s", data)
                    if "value" in data:
                        totals["energy"] = data["value"]
                else:
                    _LOGGER.error("Failed to get energy totals: %d", response.status)

            # Fetch negative_energy (fed to grid)
            params = {"measures": "negative_energy"}
            async with self.session.get(
                url, params=params, headers=headers
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    _LOGGER.debug("Negative energy totals response: %s", data)
                    if "value" in data:
                        totals["negative_energy"] = data["value"]
                else:
                    _LOGGER.error(
                        "Failed to get negative_energy totals: %d", response.status
                    )
        except OSError as err:
            _LOGGER.error("Error getting totals: %s", err)
            return None

        return totals if totals else None

    async def async_get_hourly_data(
        self,
        start_date: datetime | None = None,
        num_days: int = 1,
    ) -> dict[str, Any] | None:
        """Get hourly energy data for multiple days.

        Args:
            start_date: Start date for data retrieval (defaults to today)
            num_days: Number of days to fetch (default 1)

        Returns:
            Dictionary containing hourly energy data
        """
        if not self.token or not self.bridge_id or not self.device_id:
            return None

        try:
            if start_date is None:
                start_date = datetime.now()

            # Format as ISO 8601 datetime with Z suffix for UTC
            # The API expects: start_dateT23:00:00Z/PT{days}H format
            # So we use start_date at 23:00 UTC of previous day for 24-hour window
            duration_start = start_date.replace(
                hour=23, minute=0, second=0, microsecond=0
            )
            duration_hours = num_days * 24

            duration_str = f"{duration_start.isoformat()}Z/PT{duration_hours}H"

            url = (
                f"{ENERGY_TRACKING_URL}/historical-data/"
                f"{self.bridge_id}/{self.device_id}/hourly"
            )

            params = {
                "duration": duration_str,
                "measures": "energy,negative_energy",
            }

            headers = self._get_auth_headers()

            async with self.session.get(
                url, params=params, headers=headers
            ) as response:
                if response.status == 200:
                    return await response.json()
                _LOGGER.error("Failed to get hourly data: %d", response.status)
                return None
        except OSError as err:
            _LOGGER.error("Error getting hourly data: %s", err)
            return None

    async def async_get_meter_data(self) -> dict[str, Any] | None:
        """Get meter reading data (Zählerstand)."""
        if not self.token or not self.bridge_id or not self.device_id:
            return None

        try:
            # Dynamic duration: a 6-hour window ending now
            # Meter readings represent the total state at points in time
            now = datetime.now()
            start_time = now - timedelta(hours=6)
            # Format: 2026-01-18T08:55:11.896Z
            start_time_str = start_time.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
            duration_str = f"{start_time_str}/PT6H"

            url = (
                f"{ENERGY_TRACKING_URL}/historical-data/"
                f"{self.bridge_id}/{self.device_id}/meter"
            )

            params = {
                "duration": duration_str,
                "measures": "energy",
            }

            headers = self._get_auth_headers()

            async with self.session.get(
                url, params=params, headers=headers
            ) as response:
                if response.status == 200:
                    return await response.json()
                _LOGGER.error("Failed to get meter data: %d", response.status)
                return None
        except OSError as err:
            _LOGGER.error("Error getting meter data: %s", err)
            return None

    def _get_auth_headers(self) -> dict[str, str]:
        """Get headers with authorization token."""
        accept_header = (
            "application/vnd.obi.companion.energy-tracking.historical-record.v1+json"
        )
        return {
            "Accept": accept_header,
            "Accept-Encoding": "gzip",
            "User-Agent": "app_client",
            "Authorization": f"Bearer {self.token}",
            "Connection": "Keep-Alive",
        }
