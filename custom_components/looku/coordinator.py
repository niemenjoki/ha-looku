"""Polls the sites list, each site's summary and, for shops, the shop summary."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import LookuAuthError, LookuClient, LookuError, LookuNotFoundError
from .const import CONF_RANGE, DEFAULT_RANGE, DOMAIN, MODULE_SHOP, SCAN_INTERVAL

_LOGGER = logging.getLogger(__name__)

type LookuConfigEntry = ConfigEntry[LookuCoordinator]


class LookuCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """data = {"version", "sites": {site id: {"info", "summary", "meta", "shop", "currency"}}}.

    When Looku does not answer, the update fails and every entity becomes unavailable.
    """

    config_entry: LookuConfigEntry

    def __init__(self, hass: HomeAssistant, entry: LookuConfigEntry, client: LookuClient) -> None:
        super().__init__(hass, _LOGGER, config_entry=entry, name=DOMAIN, update_interval=SCAN_INTERVAL)
        self.client = client

    @property
    def range(self) -> str:
        return self.config_entry.options.get(CONF_RANGE, DEFAULT_RANGE)

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            health = await self.client.health()
            sites = await self.client.sites()
            results = await asyncio.gather(*(self._site(site) for site in sites))
        except LookuAuthError as error:
            raise ConfigEntryAuthFailed(str(error)) from error
        except LookuError as error:
            raise UpdateFailed(str(error)) from error
        return {
            "version": health.get("version"),
            # A site deleted between the two requests is left out, like one Looku no longer lists.
            "sites": {site["id"]: result for site, result in zip(sites, results, strict=True) if result is not None},
        }

    async def _site(self, site: dict[str, Any]) -> dict[str, Any] | None:
        try:
            return await self._site_totals(site)
        except LookuNotFoundError:
            return None

    async def _site_totals(self, site: dict[str, Any]) -> dict[str, Any]:
        summary = await self.client.summary(site["id"], self.range)
        shop: dict[str, Any] | None = None
        currency: str | None = None
        if MODULE_SHOP in (site.get("modules") or []):
            try:
                shop = (await self.client.report(site["id"], MODULE_SHOP, "summary", self.range)).get("data")
            except LookuNotFoundError:
                shop = None  # The module was turned off between the two requests.
            currency = (await self.client.config(site["id"])).get("currency") or None
        return {
            "info": site,
            "summary": summary.get("data") or {},
            "meta": summary.get("meta") or {},
            "shop": shop,
            "currency": currency,
        }

    def site(self, site_id: str) -> dict[str, Any] | None:
        return ((self.data or {}).get("sites") or {}).get(site_id)
