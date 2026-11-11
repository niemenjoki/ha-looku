"""Client for Looku's read API (/api/v1)."""

from __future__ import annotations

import asyncio
from typing import Any
from urllib.parse import quote

import aiohttp

TIMEOUT = aiohttp.ClientTimeout(total=20)


class LookuError(Exception):
    """Base error."""


class LookuConnectionError(LookuError):
    """Looku did not answer, or the answer was not Looku's (wrong address, port or proxy)."""


class LookuAuthError(LookuError):
    """The API key was rejected (HTTP 401)."""


class LookuNotAllowedError(LookuError):
    """Looku refused Home Assistant itself: its address is not in LOOKU_API_ALLOW (403), or the
    address Home Assistant uses is not in LOOKU_API_HOSTS (421)."""


class LookuNotFoundError(LookuError):
    """The site or report does not exist for this key (HTTP 404), e.g. a module that is off."""


def normalize_url(url: str) -> str:
    """Dashboard address without a trailing slash or the /api/v1 part, e.g. http://192.168.1.10:8788."""
    url = url.strip().rstrip("/")
    if url.endswith("/api/v1"):
        url = url[: -len("/api/v1")]
    return url


def normalize_key(key: str) -> str:
    """The key as Looku prints it (lk_…); a pasted "Bearer lk_…" works too."""
    key = key.strip()
    return key[len("Bearer ") :].strip() if key.lower().startswith("bearer ") else key


class LookuClient:
    """Reads totals. The integration never changes settings or keys, so a read key is enough."""

    def __init__(self, session: aiohttp.ClientSession, url: str, api_key: str, verify_ssl: bool = True) -> None:
        self._session = session
        self._base = normalize_url(url) + "/api/v1"
        self._headers = {"Authorization": f"Bearer {normalize_key(api_key)}", "Accept": "application/json"}
        self._ssl = True if verify_ssl else False

    async def _get(self, path: str, params: dict[str, str] | None = None) -> dict[str, Any]:
        try:
            async with self._session.get(
                self._base + path, headers=self._headers, params=params, timeout=TIMEOUT, ssl=self._ssl
            ) as response:
                if response.status == 401:
                    raise LookuAuthError("Looku rejected the API key.")
                if response.status in (403, 421):
                    raise LookuNotAllowedError(
                        f"Looku refused the request (HTTP {response.status}). Allow Home Assistant in "
                        "LOOKU_API_ALLOW and the address it uses in LOOKU_API_HOSTS."
                    )
                if response.status == 404:
                    raise LookuNotFoundError(f"Not found: {path}")
                if response.status != 200:
                    raise LookuConnectionError(f"Looku answered HTTP {response.status} to {path}.")
                body = await response.json(content_type=None)
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as error:
            raise LookuConnectionError(f"No valid answer from Looku: {error}") from error
        if not isinstance(body, dict):
            raise LookuConnectionError("Looku returned an unexpected answer.")
        return body

    async def health(self) -> dict[str, Any]:
        """Status and version of Looku."""
        return await self._get("/health")

    async def sites(self) -> list[dict[str, Any]]:
        """The sites this key may read. Needs a valid key and an allowed address, so it also checks the setup."""
        body = await self._get("/sites")
        data = body.get("data")
        if not isinstance(data, list):
            raise LookuConnectionError("Looku returned an unexpected list of sites.")
        return [site for site in data if isinstance(site, dict) and site.get("id")]

    async def summary(self, site: str, range_: str) -> dict[str, Any]:
        return await self._get(f"/sites/{quote(site, safe='')}/summary", {"range": range_})

    async def report(self, site: str, module: str, report: str, range_: str) -> dict[str, Any]:
        return await self._get(f"/sites/{quote(site, safe='')}/reports/{module}/{report}", {"range": range_})

    async def config(self, site: str) -> dict[str, Any]:
        """Dashboard settings of a site (read only here): the shop currency."""
        body = await self._get(f"/sites/{quote(site, safe='')}/config")
        data = body.get("data")
        return data if isinstance(data, dict) else {}
