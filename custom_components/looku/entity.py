"""Base entities: the Looku server itself, and each site as its own device."""

from __future__ import annotations

from typing import Any

from homeassistant.const import CONF_URL
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import normalize_url
from .const import DOMAIN
from .coordinator import LookuCoordinator

# Home Assistant 2026.8 and newer link a child device by registry id; via_device is removed in 2027.8.
HAS_VIA_DEVICE_ID = "via_device_id" in DeviceInfo.__annotations__


def server_device_info(coordinator: LookuCoordinator) -> DeviceInfo:
    """The Looku server (one per config entry)."""
    entry = coordinator.config_entry
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=entry.title,
        manufacturer="Looku",
        model="Looku",
        sw_version=(coordinator.data or {}).get("version"),
        entry_type=DeviceEntryType.SERVICE,
        configuration_url=normalize_url(entry.data[CONF_URL]),
    )


def link_to_server(coordinator: LookuCoordinator) -> dict:
    """DeviceInfo fields that make a site a child of the Looku server device."""
    entry = coordinator.config_entry
    if not HAS_VIA_DEVICE_ID:
        return {"via_device": (DOMAIN, entry.entry_id)}
    hub = dr.async_get(coordinator.hass).async_get_or_create(
        config_entry_id=entry.entry_id, **server_device_info(coordinator)
    )
    return {"via_device_id": hub.id}


def site_url(domain: Any) -> str | None:
    """The site's own address for the device page, from the domain Looku knows (e.g. example.com)."""
    if not isinstance(domain, str) or not domain.strip():
        return None
    domain = domain.strip()
    return domain if domain.startswith(("http://", "https://")) else f"https://{domain}"


class LookuServerEntity(CoordinatorEntity[LookuCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: LookuCoordinator, key: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = server_device_info(coordinator)


class LookuSiteEntity(CoordinatorEntity[LookuCoordinator]):
    """An entity of one site. Unavailable while Looku does not list the site for this key."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: LookuCoordinator, site: dict[str, Any], key: str) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self.site_id: str = site["id"]
        self._attr_unique_id = f"{entry.entry_id}_{self.site_id}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{entry.entry_id}_{self.site_id}")},
            name=site.get("name") or self.site_id,
            manufacturer="Looku",
            model="Site",
            entry_type=DeviceEntryType.SERVICE,
            configuration_url=site_url(site.get("domain")),
            **link_to_server(coordinator),
        )

    @property
    def site(self) -> dict[str, Any] | None:
        return self.coordinator.site(self.site_id)

    @property
    def available(self) -> bool:
        return super().available and self.site is not None
