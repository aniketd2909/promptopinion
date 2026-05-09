"""FindPatient — search FHIR for a patient by name."""

from __future__ import annotations

from typing import Annotated, Optional

from mcp.server.fastmcp import Context
from pydantic import Field

from mcp_app.fhir_client import FhirClient
from mcp_app.fhir_context import get_fhir_context


async def find_patient(
    firstName: Annotated[str, Field(description="The patient's first (given) name")],  # noqa: N803
    lastName: Annotated[  # noqa: N803
        Optional[str],
        Field(description="The patient's last (family) name. Optional."),
    ] = None,
    ctx: Context = None,
) -> str:
    fhir_context = get_fhir_context(ctx)
    if not fhir_context:
        raise ValueError(
            "No FHIR context found. The platform must send the "
            "x-fhir-server-url and x-fhir-access-token headers."
        )

    fhir_client = FhirClient(base_url=fhir_context.url, token=fhir_context.token)

    matches = await _search_patients(fhir_client, firstName, lastName)
    if not matches:
        # Try swapping in case the names were entered in the wrong order.
        matches = await _search_patients(fhir_client, lastName, firstName)

    if not matches:
        raise ValueError("No patient could be found with that name.")

    if len(matches) > 1:
        sample = ", ".join(_format_patient(p) for p in matches[:5])
        raise ValueError(
            f"Multiple patients matched ({len(matches)} total). Provide more "
            f"identifying details. First five: {sample}"
        )

    patient = matches[0]
    return _format_patient(patient, include_id=True)


async def _search_patients(
    fhir_client: FhirClient,
    given: Optional[str],
    family: Optional[str],
):
    if not given and not family:
        return []
    params = {}
    if given:
        params["given"] = given
    if family:
        params["family"] = family
    bundle = await fhir_client.search("Patient", params)
    if not bundle or not bundle.get("entry"):
        return []
    return [e["resource"] for e in bundle["entry"] if e.get("resource")]


def _format_patient(patient: dict, include_id: bool = False) -> str:
    names = patient.get("name") or []
    label = "?"
    for n in names:
        family = n.get("family") or ""
        given = " ".join(n.get("given") or [])
        label = f"{given} {family}".strip() or label
        break
    parts = [label]
    if patient.get("birthDate"):
        parts.append(f"DOB {patient['birthDate']}")
    if include_id and patient.get("id"):
        parts.append(f"id={patient['id']}")
    return " · ".join(parts)
