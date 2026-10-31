"""Data update coordinator for Obi EnergyTracker."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import logging
from typing import Any

from homeassistant.components.recorder.models import (
    StatisticData,
    StatisticMetaData,
)
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
)
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util
from homeassistant.util import slugify

from .api import STANDBY_INTERVALS, ObiEnergyTrackerAPI
from .const import DOMAIN, LIVE_TIMEOUT
from .live import ObiLiveMode

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(minutes=5)
DEVICE_INFO_INTERVAL = timedelta(minutes=30)
PRICE_REFRESH_INTERVAL = timedelta(hours=1)


class ObiEnergyTrackerCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Data update coordinator for Obi EnergyTracker."""

    def __init__(
        self,
        hass: HomeAssistant,
        api: ObiEnergyTrackerAPI,
        config_entry: Any,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=SCAN_INTERVAL,
            config_entry=config_entry,
        )
        self.api = api
        self.live = ObiLiveMode(hass, api, LIVE_TIMEOUT)
        self._cached_device: dict[str, Any] | None = None
        self._device_polls_remaining: int = 0
        self._last_price_refresh: datetime | None = None
        self._prices: dict[str, float] = {}
        self._firmware_data: dict[str, Any] | None = None
        self._feed_in_last: float = 0.0

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from API.

        Retrieves:
        - Meter reading (Zählerstand) every poll cycle (5 min)
        - Device info & firmware info every ~30 min
        - Energy tariff / prices every ~1 hour
        - Updates long-term external statistics for the Energy Dashboard
        - Consumption forecast and standby power, both best-effort
        """
        try:
            meter = await self.api.async_get_meter_data()
            _LOGGER.debug("Meter data: %s", meter)

            now = dt_util.utcnow()
            if (
                self._last_price_refresh is None
                or now - self._last_price_refresh >= PRICE_REFRESH_INTERVAL
            ):
                await self._async_refresh_prices()

            # Re-fetch device info and firmware update info when cache expired
            if self._device_polls_remaining <= 0:
                new_device = await self.api.async_get_device_info()
                if new_device is not None:
                    self._cached_device = new_device
                    self._device_polls_remaining = int(
                        DEVICE_INFO_INTERVAL / SCAN_INTERVAL
                    )
                    _LOGGER.debug("Device data refreshed: %s", new_device)
                else:
                    _LOGGER.warning("Could not refresh device info; retaining cached data")

                self._firmware_data = await self.api.async_get_bridge_firmware_update()
                device = self._cached_device
            else:
                device = self._cached_device
                self._device_polls_remaining -= 1

            # Update long-term external statistics for Home Assistant Energy Dashboard
            if meter:
                await self._async_update_statistics(meter)

            # Analytics are supplementary: the API client returns None on failure
            # so that a missing forecast never takes the meter sensors down.
            forecast = await self.api.async_get_consumption_forecast() or {}

            standby_results = await asyncio.gather(
                *[self.api.async_get_standby_power(interval) for interval in STANDBY_INTERVALS]
            )
            standby = dict(zip(STANDBY_INTERVALS, standby_results))

            return {
                "meter": meter,
                "device": device,
                "firmware": self._firmware_data,
                "prices": self._prices,
                "forecast": forecast,
                "standby": standby,
            }
        except Exception as err:
            _LOGGER.error("Failed to update data: %s", err)
            raise UpdateFailed(f"Failed to update data: {err}") from err

    async def _async_refresh_prices(self) -> None:
        """Fetch electricity prices and feed-in compensation from OBI account."""
        response = await self.api.async_get_energy_consumer()
        self._last_price_refresh = dt_util.utcnow()
        if response and isinstance(response, dict):
            # The API wraps the tariff object in an "energyConsumer" key:
            # {"energyConsumer": {"kwhPrice": "31.80", "feedInCompensation": "8.00", ...}}
            consumer = response.get("energyConsumer") or response
            kwh_price = consumer.get("kwhPrice") or consumer.get("kwh_price")
            feed_in = consumer.get("feedInCompensation") or consumer.get("feed_in_compensation")
            if kwh_price is not None:
                try:
                    # API value is in cent/kWh; convert to €/kWh for statistics.
                    self._prices["consumption"] = float(kwh_price) / 100
                except (ValueError, TypeError):
                    pass
            if feed_in is not None:
                try:
                    # API value is in cent/kWh; convert to €/kWh for statistics.
                    self._prices["feed_in"] = float(feed_in) / 100
                except (ValueError, TypeError):
                    pass
            _LOGGER.debug("Energy prices refreshed: %s", self._prices)

    async def _async_update_statistics(self, meter_data: Any) -> None:
        """Write external long-term statistics for the HA Energy dashboard."""
        device_id = self.api.device_id or "sensor"
        slug_dev = slugify(device_id)

        records = meter_data if isinstance(meter_data, list) else [meter_data]
        records = [r for r in records if isinstance(r, dict)]
        if not records:
            return

        energy_records = [r for r in records if r.get("measure") == "energy" or "energy" in r or "value" in r]
        feed_in_records = [r for r in records if r.get("measure") == "negative_energy"]

        if not energy_records:
            return

        # Consumption statistics
        consumption_stats: list[StatisticData] = []
        cost_stats: list[StatisticData] = []
        kwh_price = self._prices.get("consumption")

        for record in energy_records:
            val = record.get("value") if "value" in record else record.get("energy")
            time_str = record.get("time") or record.get("recordedAt")
            if val is None or not time_str:
                continue

            try:
                dt_record = dt_util.parse_datetime(str(time_str))
                if not dt_record:
                    continue
                start = dt_record.replace(minute=0, second=0, microsecond=0)
                energy_val = float(val)

                consumption_stats.append(
                    StatisticData(
                        start=start,
                        state=energy_val,
                        sum=energy_val,
                    )
                )

                if kwh_price is not None:
                    # Cost in EUR: (Wh / 1000) * EUR/kWh
                    cost_val = (energy_val / 1000.0) * kwh_price
                    cost_stats.append(
                        StatisticData(
                            start=start,
                            state=cost_val,
                            sum=cost_val,
                        )
                    )
            except (ValueError, TypeError):
                continue

        if consumption_stats:
            meta_consumption = StatisticMetaData(
                has_mean=False,
                has_sum=True,
                name="OBI Energy Consumption",
                source=DOMAIN,
                statistic_id=f"{DOMAIN}:{slug_dev}_consumption",
                unit_of_measurement=UnitOfEnergy.WATT_HOUR,
            )
            async_add_external_statistics(self.hass, meta_consumption, consumption_stats)

            if cost_stats:
                meta_cost = StatisticMetaData(
                    has_mean=False,
                    has_sum=True,
                    name="OBI Energy Consumption Cost",
                    source=DOMAIN,
                    statistic_id=f"{DOMAIN}:{slug_dev}_consumption_cost",
                    unit_of_measurement="EUR",
                )
                async_add_external_statistics(self.hass, meta_cost, cost_stats)

        # Feed-in statistics
        feed_in_stats: list[StatisticData] = []
        if feed_in_records:
            for record in feed_in_records:
                val = record.get("value")
                time_str = record.get("time") or record.get("recordedAt")
                if val is None or not time_str:
                    continue
                try:
                    dt_record = dt_util.parse_datetime(str(time_str))
                    if not dt_record:
                        continue
                    start = dt_record.replace(minute=0, second=0, microsecond=0)
                    feed_val = float(val)
                    self._feed_in_last = feed_val
                    feed_in_stats.append(
                        StatisticData(
                            start=start,
                            state=feed_val,
                            sum=feed_val,
                        )
                    )
                except (ValueError, TypeError):
                    continue
        else:
            # Zero-fill feed-in for non-PV accounts at the consumption timestamps
            # so HA Energy dashboard selector is always populated and never empty.
            for c_stat in consumption_stats:
                feed_in_stats.append(
                    StatisticData(
                        start=c_stat["start"],
                        state=self._feed_in_last,
                        sum=self._feed_in_last,
                    )
                )

        if feed_in_stats:
            meta_feed_in = StatisticMetaData(
                has_mean=False,
                has_sum=True,
                name="OBI Energy Feed-in",
                source=DOMAIN,
                statistic_id=f"{DOMAIN}:{slug_dev}_feed_in",
                unit_of_measurement=UnitOfEnergy.WATT_HOUR,
            )
            async_add_external_statistics(self.hass, meta_feed_in, feed_in_stats)

    async def async_import_history(self) -> None:
        """Import long-term meter history in the background on startup."""
        _LOGGER.debug("Starting background historical statistics import...")
        try:
            history = await self.api.async_get_meter_data(window=timedelta(days=30))
            if history:
                await self._async_update_statistics(history)
                _LOGGER.info("Historical statistics successfully imported into Energy dashboard")
        except Exception as err:
            _LOGGER.debug("Background history import completed with note: %s", err)
