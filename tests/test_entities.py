from aiohttp import ClientConnectionError
from freezegun.api import FrozenDateTimeFactory

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.helpers import device_registry as dr
from homeassistant.setup import async_setup_component

from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.looku.const import DOMAIN, SCAN_INTERVAL

from .conftest import API, load, make_entry, mock_looku


async def setup(hass, config_entry):
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()


async def poll(hass, freezer: FrozenDateTimeFactory):
    freezer.tick(SCAN_INTERVAL)
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)


async def test_site_totals(hass, aioclient_mock, config_entry):
    mock_looku(aioclient_mock)
    await setup(hass, config_entry)

    assert hass.states.get("sensor.example_shop_page_views_7d").state == "1830"
    assert hass.states.get("sensor.example_shop_visitors_7d").state == "640"
    assert hass.states.get("sensor.example_shop_sessions_7d").state == "702"
    assert hass.states.get("sensor.example_shop_pages_per_session_7d").state == "2.61"
    state = hass.states.get("sensor.example_shop_page_views_7d")
    assert state.attributes["from"] == "2026-11-05"
    assert state.attributes["to"] == "2026-11-11"
    assert state.attributes["state_class"] == "measurement"
    assert "sample" not in state.attributes
    assert hass.states.get("sensor.example_shop_last_page_view").state == "2026-11-11T09:02:41+00:00"
    assert hass.states.get("sensor.looku_192_0_2_10_8788_last_page_view").state == "2026-11-11T09:02:41+00:00"


async def test_visitors_off_gives_unknown_not_zero(hass, aioclient_mock, config_entry):
    """With site:visitors off Looku returns null for visitors and sessions: the state is unknown, not 0."""
    mock_looku(aioclient_mock)
    await setup(hass, config_entry)
    assert hass.states.get("sensor.my_blog_page_views_7d").state == "412"
    assert hass.states.get("sensor.my_blog_visitors_7d").state == STATE_UNKNOWN
    assert hass.states.get("sensor.my_blog_sessions_7d").state == STATE_UNKNOWN
    assert hass.states.get("sensor.my_blog_pages_per_session_7d").state == STATE_UNKNOWN


async def test_shop_sensors_only_for_shops(hass, aioclient_mock, config_entry):
    mock_looku(aioclient_mock)
    await setup(hass, config_entry)

    assert hass.states.get("sensor.example_shop_orders_7d").state == "9"
    revenue = hass.states.get("sensor.example_shop_revenue_7d")
    assert revenue.state == "312.4"
    assert revenue.attributes["unit_of_measurement"] == "EUR"
    assert revenue.attributes["device_class"] == "monetary"
    assert hass.states.get("sensor.example_shop_average_order_7d").state == "34.71"
    conversion = hass.states.get("sensor.example_shop_conversion_7d")
    assert conversion.state == "1.28"
    assert conversion.attributes["unit_of_measurement"] == "%"
    # The blog has no shop module: no shop sensors, and its shop report is never asked for.
    assert hass.states.get("sensor.my_blog_orders_7d") is None
    assert not any("/sites/blog/reports/" in str(call[1]) for call in aioclient_mock.mock_calls)


async def test_shop_without_currency(hass, aioclient_mock, config_entry):
    config = load("config_shop.json")
    config["data"]["currency"] = ""
    aioclient_mock.get(f"{API}/sites/shop/config", json=config)
    mock_looku(aioclient_mock)
    await setup(hass, config_entry)
    revenue = hass.states.get("sensor.example_shop_revenue_7d")
    assert revenue.state == "312.4"
    assert "unit_of_measurement" not in revenue.attributes
    assert "device_class" not in revenue.attributes


async def test_devices(hass, aioclient_mock, config_entry):
    mock_looku(aioclient_mock)
    await setup(hass, config_entry)
    registry = dr.async_get(hass)
    server = registry.async_get_device(identifiers={(DOMAIN, config_entry.entry_id)})
    assert server.sw_version == "0.9.0"
    assert server.configuration_url == "http://192.0.2.10:8788"
    shop = registry.async_get_device(identifiers={(DOMAIN, f"{config_entry.entry_id}_shop")})
    assert shop.name == "Example shop"
    assert shop.configuration_url == "https://shop.example.com"
    assert shop.via_device_id == server.id


async def test_looku_down_makes_entities_unavailable(hass, aioclient_mock, config_entry, freezer):
    mock_looku(aioclient_mock)
    await setup(hass, config_entry)
    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{API}/health", exc=ClientConnectionError())
    await poll(hass, freezer)
    assert hass.states.get("sensor.example_shop_page_views_7d").state == STATE_UNAVAILABLE

    aioclient_mock.clear_requests()
    mock_looku(aioclient_mock)
    await poll(hass, freezer)
    assert hass.states.get("sensor.example_shop_page_views_7d").state == "1830"


async def test_setup_retries_while_looku_is_down(hass, aioclient_mock, config_entry):
    aioclient_mock.get(f"{API}/health", exc=ClientConnectionError())
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_rejected_key_starts_reauth(hass, aioclient_mock, config_entry, freezer):
    mock_looku(aioclient_mock)
    await setup(hass, config_entry)
    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{API}/health", json={"status": "ok", "version": "0.9.0"})
    aioclient_mock.get(f"{API}/sites", status=401, json={"error": "Invalid API key."})
    await poll(hass, freezer)
    flows = hass.config_entries.flow.async_progress()
    assert [flow["context"]["source"] for flow in flows] == ["reauth"]


async def test_new_site_and_removed_site(hass, aioclient_mock, config_entry, freezer):
    only_blog = load("sites.json")
    only_blog["data"] = only_blog["data"][:1]
    mock_looku(aioclient_mock, sites=only_blog)
    await setup(hass, config_entry)
    assert hass.states.get("sensor.example_shop_page_views_7d") is None

    # The shop appears in Looku: the entry reloads and its sensors are added.
    aioclient_mock.clear_requests()
    mock_looku(aioclient_mock)
    await poll(hass, freezer)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert hass.states.get("sensor.example_shop_page_views_7d").state == "1830"
    assert hass.states.get("sensor.example_shop_orders_7d").state == "9"

    # The blog disappears from the key's sites: its sensors go unavailable, the rest keep working.
    only_shop = load("sites.json")
    only_shop["data"] = only_shop["data"][1:]
    aioclient_mock.clear_requests()
    mock_looku(aioclient_mock, sites=only_shop)
    await poll(hass, freezer)
    assert hass.states.get("sensor.my_blog_page_views_7d").state == STATE_UNAVAILABLE
    assert hass.states.get("sensor.example_shop_page_views_7d").state == "1830"


async def test_sample_flag_is_shown(hass, aioclient_mock, config_entry):
    summary = load("summary_shop.json")
    summary["meta"]["sample"] = True
    aioclient_mock.get(f"{API}/sites/shop/summary", params={"range": "7d"}, json=summary)
    mock_looku(aioclient_mock)
    await setup(hass, config_entry)
    assert hass.states.get("sensor.example_shop_page_views_7d").attributes["sample"] is True


async def test_unload(hass, aioclient_mock, config_entry):
    mock_looku(aioclient_mock)
    await setup(hass, config_entry)
    assert await hass.config_entries.async_unload(config_entry.entry_id)
    assert config_entry.state is ConfigEntryState.NOT_LOADED


async def test_currency_follows_the_site_setting(hass, aioclient_mock, config_entry, freezer):
    """The shop currency can be set or changed in Looku after setup: the unit follows without a restart."""
    no_currency = load("config_shop.json")
    no_currency["data"]["currency"] = ""
    aioclient_mock.get(f"{API}/sites/shop/config", json=no_currency)
    mock_looku(aioclient_mock)
    await setup(hass, config_entry)
    assert "unit_of_measurement" not in hass.states.get("sensor.example_shop_revenue_7d").attributes

    usd = load("config_shop.json")
    usd["data"]["currency"] = "USD"
    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{API}/sites/shop/config", json=usd)
    mock_looku(aioclient_mock)
    await poll(hass, freezer)
    revenue = hass.states.get("sensor.example_shop_revenue_7d")
    assert revenue.attributes["unit_of_measurement"] == "USD"
    assert revenue.attributes["device_class"] == "monetary"


async def test_one_missing_site_does_not_break_the_others(hass, aioclient_mock, config_entry, freezer):
    """A site deleted between the sites list and its summary is left out; the other sites keep working."""
    mock_looku(aioclient_mock)
    await setup(hass, config_entry)
    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{API}/sites/blog/summary", params={"range": "7d"}, status=404, json={"error": "Unknown site."})
    mock_looku(aioclient_mock)
    await poll(hass, freezer)
    assert hass.states.get("sensor.my_blog_page_views_7d").state == STATE_UNAVAILABLE
    assert hass.states.get("sensor.example_shop_page_views_7d").state == "1830"


async def test_last_24_hours_shows_the_times(hass, aioclient_mock):
    window = {"from": "2026-11-10", "to": "2026-11-11", "since": "2026-11-10T09:05:00.000Z", "until": "2026-11-11T09:05:00.000Z"}
    summary = load("summary_shop.json")
    summary["meta"]["range"] = window
    aioclient_mock.get(f"{API}/sites/shop/summary", params={"range": "24h"}, json=summary)
    mock_looku(aioclient_mock, range_="24h")
    entry = make_entry({"range": "24h"})
    await setup(hass, entry)
    state = hass.states.get("sensor.example_shop_page_views_24h")
    assert state.state == "1830"
    assert state.attributes["since"] == "2026-11-10T09:05:00.000Z"
    assert state.attributes["until"] == "2026-11-11T09:05:00.000Z"


async def test_server_last_page_view_covers_only_the_keys_sites(hass, aioclient_mock, config_entry):
    """With a key limited to one site, the server sensor shows that site only, not /health's newest of all sites."""
    only_blog = load("sites.json")
    only_blog["data"] = only_blog["data"][:1]
    mock_looku(aioclient_mock, sites=only_blog)
    await setup(hass, config_entry)
    assert hass.states.get("sensor.looku_192_0_2_10_8788_last_page_view").state == "2026-11-11T08:14:03+00:00"


async def test_remove_devices(hass, aioclient_mock, config_entry, hass_ws_client):
    assert await async_setup_component(hass, "config", {})
    only_shop = load("sites.json")
    mock_looku(aioclient_mock)
    await setup(hass, config_entry)
    registry = dr.async_get(hass)
    blog = registry.async_get_device(identifiers={(DOMAIN, f"{config_entry.entry_id}_blog")})
    shop = registry.async_get_device(identifiers={(DOMAIN, f"{config_entry.entry_id}_shop")})
    server = registry.async_get_device(identifiers={(DOMAIN, config_entry.entry_id)})
    client = await hass_ws_client(hass)

    async def remove(device) -> bool:
        await client.send_json_auto_id(
            {"type": "config/device_registry/remove_config_entry", "config_entry_id": config_entry.entry_id, "device_id": device.id}
        )
        return (await client.receive_json())["success"]

    # Sites Looku still lists, and the server, cannot be deleted.
    assert not await remove(shop)
    assert not await remove(server)
    # The blog disappears from Looku: its device can be deleted.
    only_shop["data"] = only_shop["data"][1:]
    aioclient_mock.clear_requests()
    mock_looku(aioclient_mock, sites=only_shop)
    await config_entry.runtime_data.async_refresh()
    assert await remove(blog)
