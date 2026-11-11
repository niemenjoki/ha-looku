"""Config flow: dashboard address and a read key. Options: the period the totals cover."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from urllib.parse import urlparse

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_API_KEY, CONF_URL, CONF_VERIFY_SSL
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import (
    LookuAuthError,
    LookuClient,
    LookuError,
    LookuNotAllowedError,
    normalize_key,
    normalize_url,
)
from .const import CONF_RANGE, DEFAULT_RANGE, DOMAIN, RANGES

USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_URL): selector.TextSelector(selector.TextSelectorConfig(type=selector.TextSelectorType.URL)),
        vol.Required(CONF_API_KEY): selector.TextSelector(
            selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
        ),
        vol.Required(CONF_VERIFY_SSL, default=True): bool,
    }
)

RECONFIGURE_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_URL): selector.TextSelector(selector.TextSelectorConfig(type=selector.TextSelectorType.URL)),
        vol.Optional(CONF_API_KEY): selector.TextSelector(
            selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
        ),
        vol.Required(CONF_VERIFY_SSL, default=True): bool,
    }
)


def clean(data: Mapping[str, Any]) -> dict[str, Any]:
    return {
        CONF_URL: normalize_url(data[CONF_URL]),
        CONF_API_KEY: normalize_key(data[CONF_API_KEY]),
        CONF_VERIFY_SSL: data.get(CONF_VERIFY_SSL, True),
    }


class LookuConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> LookuOptionsFlow:
        return LookuOptionsFlow()

    async def _validate(self, data: dict[str, Any]) -> str | None:
        """None when the key works and can read at least one site, otherwise the error key."""
        if urlparse(data[CONF_URL]).scheme not in ("http", "https") or not urlparse(data[CONF_URL]).netloc:
            return "invalid_url"
        client = LookuClient(
            async_get_clientsession(self.hass, verify_ssl=data[CONF_VERIFY_SSL]),
            data[CONF_URL],
            data[CONF_API_KEY],
            data[CONF_VERIFY_SSL],
        )
        try:
            sites = await client.sites()
        except LookuAuthError:
            return "invalid_auth"
        except LookuNotAllowedError:
            return "not_allowed"
        except LookuError:
            return "cannot_connect"
        return None if sites else "no_sites"

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            data = clean(user_input)
            await self.async_set_unique_id(data[CONF_URL].lower())
            self._abort_if_unique_id_configured()
            if (error := await self._validate(data)) is None:
                return self.async_create_entry(title=f"Looku {urlparse(data[CONF_URL]).netloc}", data=data)
            errors["base"] = error
        return self.async_show_form(
            step_id="user", data_schema=self.add_suggested_values_to_schema(USER_SCHEMA, user_input), errors=errors
        )

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """New address of the dashboard. The key may stay empty to keep the current one."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            data = clean({**user_input, CONF_API_KEY: user_input.get(CONF_API_KEY) or entry.data[CONF_API_KEY]})
            unique_id = data[CONF_URL].lower()
            await self.async_set_unique_id(unique_id)
            if unique_id != entry.unique_id:
                self._abort_if_unique_id_configured()
            if (error := await self._validate(data)) is None:
                return self.async_update_reload_and_abort(entry, unique_id=unique_id, data=data)
            errors["base"] = error
        suggested = {CONF_URL: entry.data[CONF_URL], CONF_VERIFY_SSL: entry.data.get(CONF_VERIFY_SSL, True), **(user_input or {})}
        suggested.pop(CONF_API_KEY, None)
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(RECONFIGURE_SCHEMA, suggested),
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()
        if user_input is not None:
            data = clean({**entry.data, CONF_API_KEY: user_input[CONF_API_KEY]})
            if (error := await self._validate(data)) is None:
                return self.async_update_reload_and_abort(entry, data=data)
            errors["base"] = error
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_API_KEY): selector.TextSelector(
                        selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
                    )
                }
            ),
            errors=errors,
        )


class LookuOptionsFlow(OptionsFlow):
    """The period all totals cover: the last 24 hours, or 7 days, 28 days, 3 or 12 months up to today."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        schema = vol.Schema(
            {
                vol.Required(CONF_RANGE, default=DEFAULT_RANGE): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=RANGES, translation_key="range")
                ),
            }
        )
        return self.async_show_form(
            step_id="init", data_schema=self.add_suggested_values_to_schema(schema, self.config_entry.options)
        )
