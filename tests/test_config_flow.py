import pytest
from aiohttp import ClientConnectionError

from homeassistant import config_entries
from homeassistant.const import CONF_API_KEY, CONF_URL, CONF_VERIFY_SSL
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.looku.const import DOMAIN

from .conftest import API, DATA, URL, load, mock_looku


async def test_user_flow(hass, aioclient_mock):
    mock_looku(aioclient_mock)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(result["flow_id"], DATA)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Looku 192.0.2.10:8788"
    assert result["data"] == DATA
    assert aioclient_mock.mock_calls[0][3]["Authorization"] == "Bearer lk_test"
    await hass.async_block_till_done()


async def test_user_flow_cleans_the_address_and_key(hass, aioclient_mock):
    """A pasted /api/v1 address with a trailing slash and a "Bearer " key work as they are."""
    mock_looku(aioclient_mock)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_URL: f" {URL}/api/v1/ ", CONF_API_KEY: "Bearer lk_test ", CONF_VERIFY_SSL: True}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == DATA
    await hass.async_block_till_done()


@pytest.mark.parametrize(
    ("answer", "error"),
    [
        ({"status": 401, "json": {"error": "Invalid API key."}}, "invalid_auth"),
        ({"status": 403, "text": "Forbidden"}, "not_allowed"),
        ({"status": 421, "text": "Unknown host"}, "not_allowed"),
        ({"exc": ClientConnectionError()}, "cannot_connect"),
        ({"status": 200, "text": "<html>not Looku</html>"}, "cannot_connect"),
        ({"status": 502, "text": "Bad gateway"}, "cannot_connect"),
        ({"status": 200, "json": {"data": []}}, "no_sites"),
    ],
)
async def test_user_flow_errors_then_success(hass, aioclient_mock, answer, error):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    aioclient_mock.get(f"{API}/sites", **answer)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], DATA)
    assert result["errors"] == {"base": error}

    aioclient_mock.clear_requests()
    mock_looku(aioclient_mock)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], DATA)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()


async def test_address_without_scheme(hass, aioclient_mock):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {**DATA, CONF_URL: "192.0.2.10:8788"})
    assert result["errors"] == {"base": "invalid_url"}
    assert aioclient_mock.call_count == 0


async def test_duplicate_is_aborted(hass, aioclient_mock, config_entry):
    config_entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {**DATA, CONF_URL: f"{URL}/"})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reauth(hass, aioclient_mock, config_entry):
    config_entry.add_to_hass(hass)
    mock_looku(aioclient_mock)
    result = await config_entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_API_KEY: "lk_new"})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert config_entry.data[CONF_API_KEY] == "lk_new"
    await hass.async_block_till_done()


async def test_reconfigure_keeps_the_key_when_left_empty(hass, aioclient_mock, config_entry):
    config_entry.add_to_hass(hass)
    new = "https://looku.example.com"
    mock_looku(aioclient_mock, base=f"{new}/api/v1")
    result = await config_entry.start_reconfigure_flow(hass)
    assert result["step_id"] == "reconfigure"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_URL: new, CONF_VERIFY_SSL: False})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert config_entry.data == {CONF_URL: new, CONF_API_KEY: "lk_test", CONF_VERIFY_SSL: False}
    assert config_entry.unique_id == new
    assert aioclient_mock.mock_calls[0][3]["Authorization"] == "Bearer lk_test"
    await hass.async_block_till_done()


async def test_reconfigure_to_another_configured_dashboard_is_aborted(hass, aioclient_mock, config_entry):
    config_entry.add_to_hass(hass)
    other_url = "http://192.0.2.12:8788"
    MockConfigEntry(domain=DOMAIN, title="Looku", unique_id=other_url, data={**DATA, CONF_URL: other_url}).add_to_hass(hass)
    result = await config_entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_URL: other_url, CONF_VERIFY_SSL: True})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_options_change_the_period(hass, aioclient_mock, config_entry):
    mock_looku(aioclient_mock)
    mock_looku(aioclient_mock, range_="28d")
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get("sensor.example_shop_page_views_7d").state == "1830"

    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    assert result["step_id"] == "init"
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"range": "28d"})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert config_entry.options == {"range": "28d"}
    # The entry reloads: the totals of the new period are new entities, and those of the old period are removed so
    # that one history never mixes two periods.
    assert any(str(call[1]).endswith("range=28d") for call in aioclient_mock.mock_calls)
    state = hass.states.get("sensor.example_shop_page_views_28d")
    assert state.state == "1830"
    assert state.attributes["friendly_name"] == "Example shop Page views 28d"
    registry = er.async_get(hass)
    assert registry.async_get("sensor.example_shop_page_views_7d") is None
    assert registry.async_get("sensor.example_shop_last_page_view") is not None


async def test_reauth_reloads_once(hass, aioclient_mock, config_entry):
    mock_looku(aioclient_mock)
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    aioclient_mock.clear_requests()
    mock_looku(aioclient_mock)
    result = await config_entry.start_reauth_flow(hass)
    await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_API_KEY: "lk_new"})
    await hass.async_block_till_done()
    # One request to /sites for the check, one for the single reload.
    assert sum(str(call[1]).endswith("/sites") for call in aioclient_mock.mock_calls) == 2
