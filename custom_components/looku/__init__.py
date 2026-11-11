"""Page views, visitors and shop sales of your Looku sites as Home Assistant sensors."""

from __future__ import annotations

from homeassistant.const import CONF_API_KEY, CONF_URL, CONF_VERIFY_SSL, Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import DeviceEntry

from .api import LookuClient
from .const import DOMAIN, MODULE_SHOP, RANGES
from .coordinator import LookuConfigEntry, LookuCoordinator

PLATFORMS = [Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: LookuConfigEntry) -> bool:
    verify_ssl = entry.data.get(CONF_VERIFY_SSL, True)
    client = LookuClient(
        async_get_clientsession(hass, verify_ssl=verify_ssl), entry.data[CONF_URL], entry.data[CONF_API_KEY], verify_ssl
    )
    coordinator = LookuCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    _remove_other_periods(hass, entry, coordinator.range)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Reload only for a changed period: reauth and reconfigure reload the entry themselves.
    options = dict(entry.options)

    async def _options_updated(hass: HomeAssistant, entry: LookuConfigEntry) -> None:
        if dict(entry.options) != options:
            await hass.config_entries.async_reload(entry.entry_id)

    entry.async_on_unload(entry.add_update_listener(_options_updated))

    # A site added in Looku later, or a shop module turned on, gets its sensors after the next poll.
    known = _layout(coordinator)

    @callback
    def _check_layout() -> None:
        if coordinator.data and _layout(coordinator) - known:
            hass.config_entries.async_schedule_reload(entry.entry_id)

    entry.async_on_unload(coordinator.async_add_listener(_check_layout))
    return True


def _layout(coordinator: LookuCoordinator) -> set[tuple[str, bool]]:
    """(site, has shop) pairs: the entities that exist. A new pair needs a reload; a removed one only goes unavailable."""
    return {
        (site_id, MODULE_SHOP in (site["info"].get("modules") or []))
        for site_id, site in coordinator.data["sites"].items()
    }


def _remove_other_periods(hass: HomeAssistant, entry: LookuConfigEntry, current: str) -> None:
    """The totals of another period are other entities (their unique id ends with the period): remove them when the
    period changes, so the old ones do not stay behind as unavailable."""
    registry = er.async_get(hass)
    others = tuple(f"_{period}" for period in RANGES if period != current)
    for entity in er.async_entries_for_config_entry(registry, entry.entry_id):
        if entity.unique_id.endswith(others):
            registry.async_remove(entity.entity_id)


async def async_unload_entry(hass: HomeAssistant, entry: LookuConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: LookuConfigEntry, device: DeviceEntry
) -> bool:
    """A site that Looku no longer lists for this key can be deleted from its device page.

    While the entry is not loaded (Looku down, entry disabled) the current sites are not known: only site devices
    can be deleted then, not the Looku server itself.
    """
    coordinator = getattr(entry, "runtime_data", None)
    sites = (coordinator.data or {}).get("sites", {}) if coordinator else {}
    current = {f"{entry.entry_id}_{site}" for site in sites}
    return not any(domain == DOMAIN and (ident == entry.entry_id or ident in current) for domain, ident in device.identifiers)
