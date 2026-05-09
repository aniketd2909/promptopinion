"""FHIR-shaped passthrough endpoints for local development.

The MCP server and A2A agent both speak vanilla FHIR over HTTP — they expect a
real FHIR base URL with `Patient`, `Condition`, `Observation`, etc. routes.
This module wraps :class:`backend.fhir.store.LocalFHIRStore` in just enough
FHIR-shaped routes to satisfy the calls the MCP/A2A code actually makes:

    GET  /fhir/Patient?given=...&family=...
    GET  /fhir/Patient/{id}
    GET  /fhir/Encounter?subject=Patient/{id}
    GET  /fhir/Condition?subject=Patient/{id}
    GET  /fhir/Observation?subject=Patient/{id}
    GET  /fhir/MedicationStatement?subject=Patient/{id}
    GET  /fhir/MedicationRequest?subject=Patient/{id}
    GET  /fhir/AllergyIntolerance?patient=Patient/{id}
    POST /fhir                       (transaction Bundle)

Authentication is intentionally optional — in dev we accept any bearer token
or none. In production you'd point your MCP/A2A server at Prompt Opinion's
FHIR URL with their token instead.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, Request

from backend.fhir.store import LocalFHIRStore, get_store


router = APIRouter(prefix="/fhir", tags=["dev-fhir"])


def _local_store() -> LocalFHIRStore:
    """Return the local store; raise if the dev harness was started against a
    remote FHIR backend (the passthrough only makes sense over the local JSON)."""
    store = get_store()
    if not isinstance(store, LocalFHIRStore):
        raise HTTPException(
            status_code=503,
            detail="Dev FHIR passthrough requires FHIR_MODE=local",
        )
    return store


def _bundle(resources: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "resourceType": "Bundle",
        "type": "searchset",
        "total": len(resources),
        "entry": [{"resource": r} for r in resources],
    }


def _patient_matches(patient: Dict[str, Any], *, given: Optional[str], family: Optional[str], name: Optional[str]) -> bool:
    names = patient.get("name") or []
    g = (given or "").lower().strip()
    f = (family or "").lower().strip()
    n = (name or "").lower().strip()
    if not (g or f or n):
        return True
    for entry in names:
        family_l = (entry.get("family") or "").lower()
        given_l = " ".join(entry.get("given") or []).lower()
        full_l = f"{given_l} {family_l}".strip()
        # All provided fragments must match somewhere.
        ok = True
        if g and g not in given_l:
            ok = False
        if f and f not in family_l:
            ok = False
        if n and n not in full_l:
            ok = False
        if ok:
            return True
    return False


def _read_all(rt: str) -> List[Dict[str, Any]]:
    store = _local_store()
    data = store._read()  # internal: deliberate, the passthrough is dev-only
    return data.get(rt, [])


def _filter_by_subject(rt: str, patient_id: str) -> List[Dict[str, Any]]:
    ref_short = f"Patient/{patient_id}"
    out: List[Dict[str, Any]] = []
    for r in _read_all(rt):
        subject = (r.get("subject") or r.get("patient") or {}).get("reference")
        if subject == ref_short:
            out.append(r)
    return out


# -----------------------------------------------------------------------------
# Patient
# -----------------------------------------------------------------------------

@router.get("/Patient")
def search_patient(
    given: Optional[str] = Query(default=None),
    family: Optional[str] = Query(default=None),
    name: Optional[str] = Query(default=None),
    _count: int = Query(default=30, alias="_count"),
) -> Dict[str, Any]:
    matches: List[Dict[str, Any]] = []
    for p in _read_all("Patient"):
        if _patient_matches(p, given=given, family=family, name=name):
            matches.append(p)
            if len(matches) >= _count:
                break
    return _bundle(matches)


@router.get("/Patient/{patient_id}")
def read_patient(patient_id: str) -> Dict[str, Any]:
    patient = _local_store().get_patient(patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail=f"Patient/{patient_id} not found")
    return patient


# -----------------------------------------------------------------------------
# Per-resource searches
# -----------------------------------------------------------------------------

def _patient_id_from_subject(value: str) -> str:
    # Accept `Patient/abc` or just `abc`.
    return value.split("/", 1)[1] if "/" in value else value


@router.get("/Encounter")
def search_encounter(subject: Optional[str] = None, patient: Optional[str] = None) -> Dict[str, Any]:
    pid = subject or patient
    if not pid:
        return _bundle([])
    return _bundle(_filter_by_subject("Encounter", _patient_id_from_subject(pid)))


@router.get("/Condition")
def search_condition(subject: Optional[str] = None, patient: Optional[str] = None) -> Dict[str, Any]:
    pid = subject or patient
    if not pid:
        return _bundle([])
    return _bundle(_filter_by_subject("Condition", _patient_id_from_subject(pid)))


@router.get("/Observation")
def search_observation(subject: Optional[str] = None, patient: Optional[str] = None) -> Dict[str, Any]:
    pid = subject or patient
    if not pid:
        return _bundle([])
    return _bundle(_filter_by_subject("Observation", _patient_id_from_subject(pid)))


@router.get("/MedicationStatement")
def search_medication_statement(subject: Optional[str] = None, patient: Optional[str] = None) -> Dict[str, Any]:
    pid = subject or patient
    if not pid:
        return _bundle([])
    return _bundle(_filter_by_subject("MedicationStatement", _patient_id_from_subject(pid)))


@router.get("/MedicationRequest")
def search_medication_request(subject: Optional[str] = None, patient: Optional[str] = None) -> Dict[str, Any]:
    # Treat MedicationRequest as MedicationStatement in this minimal store.
    return search_medication_statement(subject=subject, patient=patient)


@router.get("/AllergyIntolerance")
def search_allergy(subject: Optional[str] = None, patient: Optional[str] = None) -> Dict[str, Any]:
    pid = subject or patient
    if not pid:
        return _bundle([])
    return _bundle(_filter_by_subject("AllergyIntolerance", _patient_id_from_subject(pid)))


# -----------------------------------------------------------------------------
# Transaction Bundle write
# -----------------------------------------------------------------------------

@router.post("")
@router.post("/")
async def transaction_bundle(request: Request) -> Dict[str, Any]:
    """Accept a FHIR transaction Bundle and persist its entries."""
    body = await request.json()
    if body.get("resourceType") != "Bundle" or body.get("type") != "transaction":
        raise HTTPException(status_code=400, detail="Expected a transaction Bundle")
    store = _local_store()
    data = store._read()
    response_entries: List[Dict[str, Any]] = []
    for entry in body.get("entry", []):
        resource = entry.get("resource") or {}
        rt = resource.get("resourceType")
        if not rt:
            continue
        if not resource.get("id"):
            resource["id"] = str(uuid.uuid4())
        data.setdefault(rt, []).append(resource)
        response_entries.append(
            {
                "response": {
                    "status": "201 Created",
                    "location": f"{rt}/{resource['id']}",
                }
            }
        )
    store._write(data)
    return {
        "resourceType": "Bundle",
        "type": "transaction-response",
        "entry": response_entries,
    }
