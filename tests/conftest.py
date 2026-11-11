"""Fixtures. Looku answers are saved in tests/fixtures/*.json (made-up sites and numbers, field names from Looku 0.9)."""

import copy
import json
from pathlib import Path

import pytest

from homeassistant.const import CONF_API_KEY, CONF_URL, CONF_VERIFY_SSL
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.looku.const import DOMAIN

FIXTURES = Path(__file__).parent / "fixtures"
URL = "http://192.0.2.10:8788"
API = f"{URL}/api/v1"
DATA = {CONF_URL: URL, CONF_API_KEY: "lk_test", CONF_VERIFY_SSL: True}


def load(name: str) -> dict:
    return copy.deepcopy(json.loads((FIXTURES / name).read_text(encoding="utf-8")))


def make_entry(options: dict | None = None) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN, title="Looku 192.0.2.10:8788", data=DATA, unique_id=URL, options=options or {}
    )


def mock_looku(aioclient_mock, range_: str = "7d", sites: dict | None = None, base: str = API) -> None:
    """Every answer of a healthy Looku with the blog and the shop of the fixtures."""
    aioclient_mock.get(f"{base}/health", json=load("health.json"))
    aioclient_mock.get(f"{base}/sites", json=sites if sites is not None else load("sites.json"))
    aioclient_mock.get(f"{base}/sites/blog/summary", params={"range": range_}, json=load("summary_blog.json"))
    aioclient_mock.get(f"{base}/sites/shop/summary", params={"range": range_}, json=load("summary_shop.json"))
    aioclient_mock.get(
        f"{base}/sites/shop/reports/shop/summary", params={"range": range_}, json=load("shop_summary.json")
    )
    aioclient_mock.get(f"{base}/sites/shop/config", json=load("config_shop.json"))


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture
def config_entry():
    return make_entry()
