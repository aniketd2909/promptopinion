"""Async FHIR R4 client used by the MCP tools.

Uses the process-wide :class:`httpx.AsyncClient` from :mod:`mcp_app.http` so
the underlying connection pool is reused across requests. Each method retries
on transient transport errors (network failures, timeouts, HTTP 429 / 5xx);
4xx responses other than 429 are surfaced immediately because retrying won't
make them succeed.

The client is short-lived: every tool call instantiates a fresh
:class:`FhirClient` with the bearer token from the inbound MCP request, so we
never hold per-patient credentials beyond a single tool invocation.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import httpx
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from mcp_app.http import get_http_client


def _is_retryable_http_error(exc: BaseException) -> bool:
    if isinstance(exc, (httpx.TransportError, httpx.TimeoutException)):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        return status == 429 or status >= 500
    return False


_retry = retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=0.5, min=0.5, max=8),
    retry=retry_if_exception(_is_retryable_http_error),
    reraise=True,
)


class FhirClient:
    def __init__(
        self,
        base_url: str,
        token: Optional[str] = None,
        http_client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self._http = http_client or get_http_client()

    def _build_url(self, path: str) -> str:
        return f"{self.base_url}/{path.lstrip('/')}"

    def _headers(self, content_type: bool = False) -> Dict[str, str]:
        headers = {"Accept": "application/fhir+json"}
        if content_type:
            headers["Content-Type"] = "application/fhir+json"
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    @_retry
    async def read(self, path: str) -> Optional[Dict[str, Any]]:
        r = await self._http.get(self._build_url(path), headers=self._headers())
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()

    @_retry
    async def search(
        self,
        resource_type: str,
        params: Optional[Dict[str, str]] = None,
    ) -> Optional[Dict[str, Any]]:
        r = await self._http.get(
            self._build_url(resource_type),
            headers=self._headers(),
            params=params,
        )
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()

    @_retry
    async def create(
        self, resource_type: str, resource: Dict[str, Any]
    ) -> Dict[str, Any]:
        r = await self._http.post(
            self._build_url(resource_type),
            headers=self._headers(content_type=True),
            json=resource,
        )
        r.raise_for_status()
        return r.json()

    @_retry
    async def update(
        self,
        resource_type: str,
        resource_id: str,
        resource: Dict[str, Any],
    ) -> Dict[str, Any]:
        r = await self._http.put(
            self._build_url(f"{resource_type}/{resource_id}"),
            headers=self._headers(content_type=True),
            json=resource,
        )
        r.raise_for_status()
        return r.json()

    @_retry
    async def post_bundle(self, bundle: Dict[str, Any]) -> Dict[str, Any]:
        r = await self._http.post(
            self._build_url(""),
            headers=self._headers(content_type=True),
            json=bundle,
        )
        r.raise_for_status()
        return r.json()
