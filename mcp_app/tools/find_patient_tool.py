"""FindPatient — search FHIR for a patient.

Search params map directly to the FHIR R4 Patient search interaction
(see https://www.hl7.org/fhir/patient.html#search and the HAPI Swagger UI).
A request from this tool is functionally equivalent to:

    GET {FHIR_BASE_URL}/Patient?name=...&family=...&given=...&birthdate=...

so any combination that works in the Swagger UI works here.
"""

from __future__ import annotations

from typing import Annotated, Any, Dict, List, Optional
from urllib.parse import urlencode

from mcp.server.fastmcp import Context
from pydantic import Field

from mcp_app.fhir_client import FhirClient
from mcp_app.fhir_context import get_fhir_context


async def find_patient(
    name: Annotated[
        Optional[str],
        Field(
            description=(
                "Broad text match across given + family + middle names. "
                "Maps to FHIR Patient?name=… (use this when you only have one "
                "name token or aren't sure which is the family name)."
            )
        ),
    ] = None,
    firstName: Annotated[  # noqa: N803
        Optional[str],
        Field(description="Maps to FHIR Patient?given=… (the given/first name)."),
    ] = None,
    lastName: Annotated[  # noqa: N803
        Optional[str],
        Field(description="Maps to FHIR Patient?family=… (the family/last name)."),
    ] = None,
    birthdate: Annotated[
        Optional[str],
        Field(
            description=(
                "Maps to FHIR Patient?birthdate=… in YYYY-MM-DD format."
            )
        ),
    ] = None,
    gender: Annotated[
        Optional[str],
        Field(
            description=(
                "Maps to FHIR Patient?gender=… — one of male | female | other | unknown."
            )
        ),
    ] = None,
    identifier: Annotated[
        Optional[str],
        Field(
            description=(
                "Maps to FHIR Patient?identifier=… (e.g. MRN, SSN). "
                "Format: 'system|value' or just 'value'."
            )
        ),
    ] = None,
    ctx: Context = None,
) -> str:
    if not any([name, firstName, lastName, birthdate, gender, identifier]):
        raise ValueError(
            "Provide at least one search field: name, firstName, lastName, "
            "birthdate, gender, or identifier."
        )

    fhir_context = get_fhir_context(ctx)
    fhir_client = FhirClient(base_url=fhir_context.url, token=fhir_context.token)

    params: Dict[str, str] = {}
    if name:
        params["name"] = name
    if firstName:
        params["given"] = firstName
    if lastName:
        params["family"] = lastName
    if birthdate:
        params["birthdate"] = birthdate
    if gender:
        params["gender"] = gender
    if identifier:
        params["identifier"] = identifier
    params["_count"] = "20"

    matches = await _search_patients(fhir_client, params)

    # Fallback: if firstName + lastName didn't match (e.g. swapped order, or
    # the name is stored as a single token), retry with FHIR's broader `name`
    # parameter combining both.
    if not matches and (firstName or lastName) and not name:
        broad_params = {
            k: v for k, v in params.items() if k not in ("given", "family")
        }
        broad_params["name"] = " ".join(filter(None, [firstName, lastName]))
        matches = await _search_patients(fhir_client, broad_params)

    if not matches:
        url = f"{fhir_client.base_url}/Patient?{urlencode(params)}"
        raise ValueError(
            f"No patient matched. Tried FHIR search: GET {url}"
        )

    if len(matches) > 1:
        sample = "; ".join(_format_patient(p, include_id=True) for p in matches[:5])
        raise ValueError(
            f"Multiple patients matched ({len(matches)} shown of up to 20). "
            f"Provide more identifying details. First five: {sample}"
        )

    return _format_patient(matches[0], include_id=True)


async def _search_patients(
    fhir_client: FhirClient,
    params: Dict[str, str],
) -> List[Dict[str, Any]]:
    bundle = await fhir_client.search("Patient", params)
    if not bundle or not bundle.get("entry"):
        return []
    return [e["resource"] for e in bundle["entry"] if e.get("resource")]


def _format_patient(patient: Dict[str, Any], include_id: bool = False) -> str:
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
    if patient.get("gender"):
        parts.append(patient["gender"])
    if include_id and patient.get("id"):
        parts.append(f"id={patient['id']}")
    return " · ".join(parts)
