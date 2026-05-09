"""Resolve FHIR context from the inbound MCP HTTP request.

The Prompt Opinion platform sends FHIR credentials as HTTP headers on every
streamable-HTTP MCP request:

    x-fhir-server-url:    https://workspace.promptopinion.ai/api/.../fhir
    x-fhir-access-token:  <bearer token>
    x-patient-id:         <patient uuid>             (optional — may be in JWT)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import jwt
from mcp.server.fastmcp import Context

from mcp_app.mcp_constants import (
    FHIR_ACCESS_TOKEN_HEADER,
    FHIR_SERVER_URL_HEADER,
    PATIENT_ID_HEADER,
)


@dataclass
class FhirContext:
    url: str
    token: Optional[str] = None


def get_fhir_context(ctx: Context) -> Optional[FhirContext]:
    req = ctx.request_context.request
    url = req.headers.get(FHIR_SERVER_URL_HEADER)
    if not url:
        return None
    return FhirContext(url=url, token=req.headers.get(FHIR_ACCESS_TOKEN_HEADER))


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
