"""Sensors: totals of the chosen period per site, shop totals for shops, and when page views last arrived."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import MODULE_SHOP
from .coordinator import LookuConfigEntry, LookuCoordinator
from .entity import LookuServerEntity, LookuSiteEntity

PARALLEL_UPDATES = 0


def parse_time(value: Any) -> datetime | None:
    return dt_util.parse_datetime(value) if isinstance(value, str) and value else None


@dataclass(frozen=True, kw_only=True)
class LookuSensorDescription(SensorEntityDescription):
    value: Callable[[dict[str, Any]], Any]
    # Totals of the chosen period: the name ends with it (e.g. "Page views 7d") and so does the unique id, so a
    # changed period makes new entities instead of mixing two different quantities in one history.
    with_range: bool = True
    # Shop totals in money get the shop currency (from the site settings) as their unit.
    money: bool = False


SITE_SENSORS = (
    LookuSensorDescription(
        key="pageviews", value=lambda s: s["summary"].get("pageviews"),
        state_class=SensorStateClass.MEASUREMENT,
    ),
    # With visitors counting off for the site (site:visitors off) Looku returns null for these: the state is unknown.
    LookuSensorDescription(
        key="visitors", value=lambda s: s["summary"].get("visitors"),
        state_class=SensorStateClass.MEASUREMENT,
    ),
    LookuSensorDescription(
        key="sessions", value=lambda s: s["summary"].get("sessions"),
        state_class=SensorStateClass.MEASUREMENT,
    ),
    LookuSensorDescription(
        key="pages_per_session", value=lambda s: s["summary"].get("pages_per_session"),
        state_class=SensorStateClass.MEASUREMENT, suggested_display_precision=2,
    ),
    LookuSensorDescription(
        key="last_pageview", value=lambda s: parse_time(s["info"].get("last_pageview")),
        device_class=SensorDeviceClass.TIMESTAMP, entity_category=EntityCategory.DIAGNOSTIC, with_range=False,
    ),
)

SHOP_SENSORS = (
    LookuSensorDescription(
        key="orders", value=lambda s: (s["shop"] or {}).get("orders"),
        state_class=SensorStateClass.MEASUREMENT,
    ),
    LookuSensorDescription(
        key="revenue", value=lambda s: (s["shop"] or {}).get("revenue"), money=True, suggested_display_precision=2,
    ),
    LookuSensorDescription(
        key="average_order", value=lambda s: (s["shop"] or {}).get("average_order"), money=True,
        suggested_display_precision=2,
    ),
    # Null (unknown) when the site counts no visitors, like sessions.
    LookuSensorDescription(
        key="conversion", value=lambda s: (s["shop"] or {}).get("conversion_pct"),
        state_class=SensorStateClass.MEASUREMENT, native_unit_of_measurement=PERCENTAGE, suggested_display_precision=2,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: LookuConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    entities: list[SensorEntity] = [LookuLastPageviewSensor(coordinator)]
    for site_data in coordinator.data["sites"].values():
        site = site_data["info"]
        entities += [LookuSiteSensor(coordinator, site, d) for d in SITE_SENSORS]
        if MODULE_SHOP in (site.get("modules") or []):
            entities += [LookuSiteSensor(coordinator, site, d) for d in SHOP_SENSORS]
    async_add_entities(entities)


class LookuSiteSensor(LookuSiteEntity, SensorEntity):
    entity_description: LookuSensorDescription

    def __init__(self, coordinator: LookuCoordinator, site: dict[str, Any], description: LookuSensorDescription) -> None:
        key = f"{description.key}_{coordinator.range}" if description.with_range else description.key
        super().__init__(coordinator, site, key)
        self._attr_translation_key = description.key
        self.entity_description = description
        if description.with_range:
            self._attr_translation_placeholders = {"range": coordinator.range}

    @property
    def currency(self) -> str | None:
        """The currency is a site setting in Looku and can change; without one the money totals are plain numbers."""
        return (self.site or {}).get("currency") if self.entity_description.money else None

    @property
    def native_unit_of_measurement(self) -> str | None:
        return self.currency or self.entity_description.native_unit_of_measurement

    @property
    def device_class(self) -> SensorDeviceClass | None:
        if self.entity_description.money:
            return SensorDeviceClass.MONETARY if self.currency else None
        return self.entity_description.device_class

    @property
    def native_value(self) -> Any:
        site = self.site
        return self.entity_description.value(site) if site else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        site = self.site
        if not site or not self.entity_description.with_range:
            return None
        period = site["meta"].get("range") or {}
        # Days for the day periods; for the last 24 hours also the exact times.
        attributes = {name: period[name] for name in ("from", "to", "since", "until") if period.get(name)}
        if site["meta"].get("sample"):
            attributes["sample"] = True
        return attributes


class LookuLastPageviewSensor(LookuServerEntity, SensorEntity):
    """The newest page view of the sites this key can read: tells whether the sites' connectors are sending."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: LookuCoordinator) -> None:
        super().__init__(coordinator, "last_pageview")

    @property
    def native_value(self) -> datetime | None:
        # From the key's own sites, not /health's last_ingest, which covers every site on the server.
        times = [
            parse_time(site["info"].get("last_pageview"))
            for site in ((self.coordinator.data or {}).get("sites") or {}).values()
        ]
        return max((t for t in times if t is not None), default=None)
