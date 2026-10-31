"""Data update coordinator for Obi EnergyTracker."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import logging
from typing import Any

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import (
    StatisticData,
    StatisticMeanType,
    StatisticMetaData,
)
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    get_last_statistics,
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
            kwh_price_raw = consumer.get("kwhPrice")
            if kwh_price_raw is None:
                kwh_price_raw = consumer.get("kwh_price")
            feed_in_raw = consumer.get("feedInCompensation")
            if feed_in_raw is None:
                feed_in_raw = consumer.get("feed_in_compensation")
            if kwh_price_raw is not None:
                try:
                    # API value is in cent/kWh; convert to €/kWh for statistics.
                    self._prices["consumption"] = float(kwh_price_raw) / 100
                except (ValueError, TypeError):
                    pass
            if feed_in_raw is not None:
                try:
                    # API value is in cent/kWh; convert to €/kWh for statistics.
                    self._prices["feed_in"] = float(feed_in_raw) / 100
                except (ValueError, TypeError):
                    pass
            _LOGGER.debug("Energy prices refreshed: %s", self._prices)

    async def _async_update_statistics(self, meter_data: Any) -> None:
        """Write external long-term statistics for the HA Energy dashboard.

        The API returns absolute cumulative meter readings (Wh since installation).
        HA's external statistics `sum` field must also be a running cumulative.  To
        anchor the new rows correctly we fetch the last known `sum` from the recorder
        and compute the offset from the first record we are about to write.

        `state` holds the per-row instantaneous meter reading; `sum` holds the
        running total so that the Energy dashboard graph stays monotonic.
        """
        device_id = self.api.device_id or "sensor"
        slug_dev = slugify(device_id)

        records = meter_data if isinstance(meter_data, list) else [meter_data]
        records = [r for r in records if isinstance(r, dict)]
        if not records:
            return

        energy_records = sorted(
            [r for r in records if r.get("measure") == "energy"],
            key=lambda r: r.get("time") or r.get("recordedAt") or "",
        )
        feed_in_records = sorted(
            [r for r in records if r.get("measure") == "negative_energy"],
            key=lambda r: r.get("time") or r.get("recordedAt") or "",
        )

        if not energy_records:
            return

        def _parse_records(
            raw: list[dict[str, Any]],
        ) -> list[tuple[datetime, float]]:
            """Parse records into (start-of-hour, value) pairs, deduped by hour."""
            seen: dict[datetime, float] = {}
            for record in raw:
                val = record.get("value")
                time_str = record.get("time") or record.get("recordedAt")
                if val is None or not time_str:
                    continue
                try:
                    dt_record = dt_util.parse_datetime(str(time_str))
                    if not dt_record:
                        continue
                    start = dt_record.replace(minute=0, second=0, microsecond=0)
                    seen[start] = float(val)
                except (ValueError, TypeError):
                    continue
            return sorted(seen.items())

        async def _get_last_sum(statistic_id: str) -> float | None:
            """Return the most recent cumulative sum stored in the recorder."""
            rows = await get_instance(self.hass).async_add_executor_job(
                get_last_statistics, self.hass, 1, statistic_id, True, {"sum"}
            )
            row = next(iter(rows.get(statistic_id, [])), None)
            return None if row is None else row.get("sum")

        def _build_stats(
            parsed: list[tuple[datetime, float]],
            last_sum: float | None,
        ) -> list[StatisticData]:
            """Build StatisticData rows with a monotonically increasing `sum`.

            The meter readings are absolute Wh values.  The first row anchors
            the cumulative sum: if the recorder already has a running total we
            shift the new rows so the sum continues from there; otherwise we
            start at 0 (HA will display relative growth, not the raw meter offset).
            """
            if not parsed:
                return []
            first_reading = parsed[0][1]
            baseline: float = (last_sum if last_sum is not None else 0.0) - first_reading
            return [
                StatisticData(start=start, state=value, sum=value + baseline)
                for start, value in parsed
            ]

        kwh_price = self._prices.get("consumption")

        # ── Consumption ──────────────────────────────────────────────────────
        consumption_id = f"{DOMAIN}:{slug_dev}_consumption"
        consumption_parsed = _parse_records(energy_records)
        last_consumption_sum = await _get_last_sum(consumption_id)
        consumption_stats = _build_stats(consumption_parsed, last_consumption_sum)

        if consumption_stats:
            async_add_external_statistics(
                self.hass,
                StatisticMetaData(
                    mean_type=StatisticMeanType.NONE,
                    has_sum=True,
                    name="OBI Energy Consumption",
                    source=DOMAIN,
                    statistic_id=consumption_id,
                    unit_of_measurement=UnitOfEnergy.WATT_HOUR,
                ),
                consumption_stats,
            )

            # ── Consumption cost ──────────────────────────────────────────────
            if kwh_price is not None:
                cost_id = f"{DOMAIN}:{slug_dev}_consumption_cost"
                last_cost_sum = await _get_last_sum(cost_id)
                cost_parsed = [
                    (start, (val / 1000.0) * kwh_price)
                    for start, val in consumption_parsed
                ]
                cost_stats = _build_stats(cost_parsed, last_cost_sum)
                if cost_stats:
                    async_add_external_statistics(
                        self.hass,
                        StatisticMetaData(
                            mean_type=StatisticMeanType.NONE,
                            has_sum=True,
                            name="OBI Energy Consumption Cost",
                            source=DOMAIN,
                            statistic_id=cost_id,
                            unit_of_measurement="EUR",
                        ),
                        cost_stats,
                    )

        # ── Feed-in ───────────────────────────────────────────────────────────
        feed_in_id = f"{DOMAIN}:{slug_dev}_feed_in"
        if feed_in_records:
            feed_in_parsed = _parse_records(feed_in_records)
        else:
            # Zero-fill feed-in for non-PV accounts at consumption timestamps so
            # the Energy dashboard selector is always populated.
            feed_in_parsed = [
                (start, self._feed_in_last) for start, _ in consumption_parsed
            ]

        if feed_in_parsed:
            # Cache the latest known feed-in value for future zero-fills.
            self._feed_in_last = feed_in_parsed[-1][1]
            last_feed_in_sum = await _get_last_sum(feed_in_id)
            feed_in_stats = _build_stats(feed_in_parsed, last_feed_in_sum)
            if feed_in_stats:
                async_add_external_statistics(
                    self.hass,
                    StatisticMetaData(
                        mean_type=StatisticMeanType.NONE,
                        has_sum=True,
                        name="OBI Energy Feed-in",
                        source=DOMAIN,
                        statistic_id=feed_in_id,
                        unit_of_measurement=UnitOfEnergy.WATT_HOUR,
                    ),
                    feed_in_stats,
                )

    async def async_import_history(self) -> None:
        """Import long-term meter history in the background on startup."""
        _LOGGER.debug("Starting background historical statistics import...")
        try:
            history = await self.api.async_get_meter_data(window=timedelta(days=30))
            if history:
                await self._async_update_statistics(history)
                _LOGGER.info(
                    "Historical statistics successfully imported into Energy dashboard"
                )
        except Exception as err:
            _LOGGER.debug("Background history import completed with note: %s", err)
