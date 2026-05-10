"""Resolve FHIR context from the inbound MCP HTTP request.

In production, the Prompt Opinion platform sends FHIR credentials as HTTP
headers on every streamable-HTTP MCP request:

    x-fhir-server-url:    https://workspace.promptopinion.ai/api/.../fhir
    x-fhir-access-token:  <bearer token>
    x-patient-id:         <patient uuid>             (optional — may be in JWT)

For local development (e.g. against the public HAPI test server), the headers
are typically absent. We then fall back to environment variables:

    FHIR_BASE_URL     — defaults to https://hapi.fhir.org/baseR4
    FHIR_ACCESS_TOKEN — optional; HAPI public has no auth
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

import jwt
from mcp.server.fastmcp import Context

from mcp_app.mcp_constants import (
    FHIR_ACCESS_TOKEN_HEADER,
    FHIR_SERVER_URL_HEADER,
    PATIENT_ID_HEADER,
)


DEFAULT_FHIR_BASE_URL = "https://hapi.fhir.org/baseR4"


@dataclass
class FhirContext:
    url: str
    token: Optional[str] = None


def get_fhir_context(ctx: Context) -> FhirContext:
    """Resolve FHIR base URL + bearer token from headers, falling back to env vars.

    Always returns a FhirContext — falls back to FHIR_BASE_URL (or HAPI public)
    when no header is present, so local dev works without platform-injected
    credentials.
    """
    req = ctx.request_context.request
    url = req.headers.get(FHIR_SERVER_URL_HEADER) or os.getenv(
        "FHIR_BASE_URL", DEFAULT_FHIR_BASE_URL
    )
    token = req.headers.get(FHIR_ACCESS_TOKEN_HEADER) or os.getenv(
        "FHIR_ACCESS_TOKEN"
    )
    return FhirContext(url=url, token=token)


def get_patient_id_if_context_exists(ctx: Context) -> Optional[str]:
    """Resolve a patient id by, in order:

    1. ``patient`` claim of the FHIR access token (SMART convention)
    2. ``x-patient-id`` header
    """
    req = ctx.request_context.request
    fhir_token = req.headers.get(FHIR_ACCESS_TOKEN_HEADER)
    if fhir_token:
        try:
            claims = jwt.decode(fhir_token, options={"verify_signature": False})
            patient = claims.get("patient")
            if patient:
                return str(patient)
        except jwt.PyJWTError:
            # Token isn't a JWT (bare opaque bearer is fine) — fall through.
            pass
    return req.headers.get(PATIENT_ID_HEADER)
