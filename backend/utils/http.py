"""MolTel — shared async httpx helpers."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator, Optional

import httpx

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 30.0
_USER_AGENT = "MolTel/1.0 (research tool; contact researcher@example.com)"


@asynccontextmanager
async def get_async_client() -> AsyncGenerator[httpx.AsyncClient, None]:
    """Context manager that yields a configured async httpx client."""
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(_DEFAULT_TIMEOUT),
        headers={"User-Agent": _USER_AGENT},
        follow_redirects=True,
    ) as client:
        yield client


async def safe_get(
    url: str,
    params: Optional[dict[str, Any]] = None,
    headers: Optional[dict[str, str]] = None,
) -> Optional[dict[str, Any]]:
    """Perform a GET request; return parsed JSON or None on failure."""
    try:
        async with get_async_client() as client:
            response = await client.get(url, params=params, headers=headers or {})
            response.raise_for_status()
            return response.json()
    except httpx.TimeoutException:
        logger.warning("Timeout when fetching %s", url)
        return None
    except httpx.HTTPStatusError as exc:
        logger.warning(
            "HTTP %s error when fetching %s", exc.response.status_code, url
        )
        return None
    except Exception as exc:  # noqa: BLE001
        logger.warning("Unexpected error when fetching %s: %s", url, exc)
        return None
