"""Process-wide shared :class:`httpx.AsyncClient`.

Constructing a fresh client per request defeats connection pooling and pays
for a TCP/TLS handshake on every FHIR call. We lazily create one client at
first use and tear it down in the FastAPI lifespan.
"""

from __future__ import annotations

from typing import Optional

import httpx


_DEFAULT_TIMEOUT = httpx.Timeout(connect=10.0, read=30.0, write=30.0, pool=5.0)
_DEFAULT_LIMITS = httpx.Limits(max_connections=100, max_keepalive_connections=20)

_client: Optional[httpx.AsyncClient] = None


def get_http_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT, limits=_DEFAULT_LIMITS)
    return _client


async def close_http_client() -> None:
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
    _client = None
