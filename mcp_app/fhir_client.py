"""Async FHIR R4 client used by the MCP tools.

Mirrors the pattern in po-community-mcp/python/fhir_client.py. The client is
short-lived: every tool call instantiates a fresh client with the bearer token
from the inbound MCP request, never holding credentials across calls.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import httpx


class FhirClient:
    def __init__(self, base_url: str, token: Optional[str] = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token

    def _build_url(self, path: str) -> str:
        return f"{self.base_url}/{path.lstrip('/')}"

    def _headers(self) -> Dict[str, str]:
        headers = {"Accept": "application/fhir+json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    async def read(self, path: str) -> Optional[Dict[str, Any]]:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.get(self._build_url(path), headers=self._headers())
            if r.status_code == 404:
                return None
            r.raise_for_status()
            return r.json()

    async def search(
        self,
        resource_type: str,
        params: Optional[Dict[str, str]] = None,
    ) -> Optional[Dict[str, Any]]:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.get(
                self._build_url(resource_type),
                headers=self._headers(),
                params=params,
            )
            if r.status_code == 404:
                return None
            r.raise_for_status()
            return r.json()

    async def post_bundle(self, bundle: Dict[str, Any]) -> Dict[str, Any]:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(
                self._build_url(""),
                headers={**self._headers(), "Content-Type": "application/fhir+json"},
                json=bundle,
            )
            r.raise_for_status()
            return r.json()
