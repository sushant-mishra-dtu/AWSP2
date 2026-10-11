"""Shared HTTP helper: sensible timeouts, one limited retry, typed errors."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from ..errors import ProviderError

TIMEOUT = httpx.Timeout(10.0, connect=5.0)
USER_AGENT = "AirWindow/0.1 (hackathon project; activity planning)"

# Tests inject an httpx.MockTransport here. Never set in production.
_transport: httpx.AsyncBaseTransport | None = None


def set_transport(transport: httpx.AsyncBaseTransport | None) -> None:
    global _transport
    _transport = transport


def client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=TIMEOUT,
        headers={"User-Agent": USER_AGENT},
        transport=_transport,
        follow_redirects=False,
    )


async def get_json(
    provider: str,
    url: str,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    retries: int = 1,
    backoff_s: float = 0.4,
    http: httpx.AsyncClient | None = None,
) -> Any:
    owns = http is None
    http = http or client()
    try:
        attempt = 0
        while True:
            try:
                r = await http.get(url, params=params, headers=headers)
            except httpx.TimeoutException as exc:
                err = ProviderError(provider, "timeout", f"request timed out ({exc.__class__.__name__})")
            except httpx.HTTPError as exc:
                err = ProviderError(provider, "network", f"network error ({exc.__class__.__name__})")
            else:
                if r.status_code == 429:
                    raise ProviderError(provider, "rate_limited", "provider rate limit reached", 429)
                if r.status_code in (401, 403):
                    raise ProviderError(provider, "http", "provider rejected credentials", r.status_code)
                if 400 <= r.status_code < 500:
                    reason = _reason(r)
                    raise ProviderError(provider, "http", f"request rejected: {reason}", r.status_code)
                if r.status_code >= 500:
                    err = ProviderError(provider, "http", f"provider error {r.status_code}", r.status_code)
                else:
                    try:
                        return r.json()
                    except ValueError:
                        raise ProviderError(provider, "bad_response", "response was not valid JSON", r.status_code)
            if attempt >= retries:
                raise err
            attempt += 1
            await asyncio.sleep(backoff_s * attempt)
    finally:
        if owns:
            await http.aclose()


def _reason(r: httpx.Response) -> str:
    try:
        body = r.json()
        if isinstance(body, dict):
            return str(body.get("reason") or body.get("detail") or body.get("message") or r.status_code)[:200]
    except ValueError:
        pass
    return str(r.status_code)
