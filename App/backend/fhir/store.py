"""FHIR resource store.

Two backends:

- ``LocalFHIRStore`` keeps everything in a single JSON file. On first run it
  ingests ``sample-patient.json`` so the demo has 13 real-shaped Patients to
  search against.
- ``RemoteFHIRStore`` is a thin pass-through to a HAPI-style FHIR server. Wired
  via ``FHIR_MODE=remote`` and ``FHIR_BASE_URL``.

Both implement the same minimal interface that the MCP server and the API
routes consume.
"""

from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol

import httpx

from backend.config import get_settings
from backend.fhir.schemas import StructuredEncounterPayload


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return str(uuid.uuid4())


class FHIRStore(Protocol):
    def search_patients(self, query: Optional[str] = None) -> List[Dict[str, Any]]: ...
    def get_patient(self, patient_id: str) -> Optional[Dict[str, Any]]: ...
    def get_patient_history(self, patient_id: str) -> List[Dict[str, Any]]: ...
    def commit_encounter(
        self,
        patient_id: str,
        payload: StructuredEncounterPayload,
        diagnosis_summary: Optional[str] = None,
    ) -> Dict[str, Any]: ...


# -----------------------------------------------------------------------------
# Bundle assembly — shared by both backends
# -----------------------------------------------------------------------------

def build_resources_from_payload(
    patient_id: str,
    payload: StructuredEncounterPayload,
    diagnosis_summary: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Translate the structurer's narrow payload into real FHIR R4 resources."""

    now = _now_iso()
    encounter_id = _new_id()
    patient_ref = {"reference": f"Patient/{patient_id}"}

    resources: List[Dict[str, Any]] = []

    encounter = {
        "resourceType": "Encounter",
        "id": encounter_id,
        "status": "finished",
        "class": {
            "system": "http://terminology.hl7.org/CodeSystem/v3-ActCode",
            "code": payload.encounter.encounter_class,
        },
        "subject": patient_ref,
        "period": {"start": now, "end": now},
        "reasonCode": [{"text": payload.encounter.reason}],
        "extension": [
            {
                "url": "https://promptopinion.ai/fhir/StructureDefinition/visit-summary",
                "valueString": payload.encounter.summary,
            }
        ],
    }
    resources.append(encounter)

    encounter_ref = {"reference": f"Encounter/{encounter_id}"}

    for obs in payload.observations:
        coding = []
        if obs.coding and (obs.coding.system or obs.coding.code):
            coding.append(
                {
                    "system": obs.coding.system,
                    "code": obs.coding.code,
                    "display": obs.coding.display,
                }
            )
        resources.append(
            {
                "resourceType": "Observation",
                "id": _new_id(),
                "status": "final",
                "code": {"text": obs.kind, **({"coding": coding} if coding else {})},
                "subject": patient_ref,
                "encounter": encounter_ref,
                "effectiveDateTime": now,
                "valueString": obs.value,
                **({"note": [{"text": obs.note}]} if obs.note else {}),
            }
        )

    for cond in payload.conditions:
        coding = []
        if cond.coding and (cond.coding.system or cond.coding.code):
            coding.append(
                {
                    "system": cond.coding.system,
                    "code": cond.coding.code,
                    "display": cond.coding.display,
                }
            )
        resources.append(
            {
                "resourceType": "Condition",
                "id": _new_id(),
                "clinicalStatus": {
                    "coding": [
                        {
                            "system": "http://terminology.hl7.org/CodeSystem/condition-clinical",
                            "code": cond.clinical_status,
                        }
                    ]
                },
                "code": {"text": cond.name, **({"coding": coding} if coding else {})},
                "subject": patient_ref,
                "encounter": encounter_ref,
                "recordedDate": now,
                **({"onsetString": cond.onset} if cond.onset else {}),
                **({"note": [{"text": cond.note}]} if cond.note else {}),
            }
        )

    for med in payload.medications:
        coding = []
        if med.coding and (med.coding.system or med.coding.code):
            coding.append(
                {
                    "system": med.coding.system,
                    "code": med.coding.code,
                    "display": med.coding.display,
                }
            )
        resources.append(
            {
                "resourceType": "MedicationStatement",
                "id": _new_id(),
                "status": med.status,
                "medicationCodeableConcept": {
                    "text": med.name,
                    **({"coding": coding} if coding else {}),
                },
                "subject": patient_ref,
                "context": encounter_ref,
                "effectiveDateTime": now,
                **(
                    {"dosage": [{"text": med.dosage}]}
                    if med.dosage
                    else {}
                ),
            }
        )

    for allergy in payload.allergies:
        resources.append(
            {
                "resourceType": "AllergyIntolerance",
                "id": _new_id(),
                "clinicalStatus": {
                    "coding": [
                        {
                            "system": "http://terminology.hl7.org/CodeSystem/allergyintolerance-clinical",
                            "code": "active",
                        }
                    ]
                },
                "code": {"text": allergy.substance},
                "patient": patient_ref,
                "recordedDate": now,
                **({"reaction": [{"description": allergy.reaction}]} if allergy.reaction else {}),
                **({"criticality": allergy.severity} if allergy.severity else {}),
            }
        )

    if diagnosis_summary:
        resources.append(
            {
                "resourceType": "ClinicalImpression",
                "id": _new_id(),
                "status": "completed",
                "subject": patient_ref,
                "encounter": encounter_ref,
                "date": now,
                "summary": diagnosis_summary,
            }
        )

    return resources


def _patient_display_name(patient: Dict[str, Any]) -> str:
    names = patient.get("name") or []
    for n in names:
        family = n.get("family") or ""
        given = " ".join(n.get("given") or [])
        if family or given:
            return f"{given} {family}".strip()
    return f"Patient/{patient.get('id', '?')}"


# -----------------------------------------------------------------------------
# Local store
# -----------------------------------------------------------------------------

class LocalFHIRStore:
    """In-process FHIR store backed by a single JSON file."""

    def __init__(self, store_path: Path, seed_bundle: Optional[Path] = None) -> None:
        self.store_path = store_path
        self.seed_bundle = seed_bundle
        self._lock = threading.Lock()
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.store_path.exists():
            self._initialize_from_seed()

    # -- internals -------------------------------------------------------

    def _initialize_from_seed(self) -> None:
        data: Dict[str, List[Dict[str, Any]]] = {
            "Patient": [],
            "Encounter": [],
            "Observation": [],
            "Condition": [],
            "MedicationStatement": [],
            "AllergyIntolerance": [],
            "ClinicalImpression": [],
        }
        if self.seed_bundle and self.seed_bundle.exists():
            with self.seed_bundle.open() as f:
                bundle = json.load(f)
            for entry in bundle.get("entry", []):
                resource = entry.get("resource") or {}
                rt = resource.get("resourceType")
                if rt and rt in data:
                    data[rt].append(resource)
        self._write(data)

    def _read(self) -> Dict[str, List[Dict[str, Any]]]:
        with self.store_path.open() as f:
            return json.load(f)

    def _write(self, data: Dict[str, List[Dict[str, Any]]]) -> None:
        tmp = self.store_path.with_suffix(".tmp")
        with tmp.open("w") as f:
            json.dump(data, f, indent=2)
        tmp.replace(self.store_path)

    # -- interface -------------------------------------------------------

    def search_patients(self, query: Optional[str] = None) -> List[Dict[str, Any]]:
        data = self._read()
        results: List[Dict[str, Any]] = []
        q = (query or "").strip().lower()
        for patient in data["Patient"]:
            display = _patient_display_name(patient).lower()
            if not q or q in display or q in (patient.get("id", "").lower()):
                results.append(
                    {
                        "id": patient["id"],
                        "name": _patient_display_name(patient),
                        "gender": patient.get("gender"),
                        "birthDate": patient.get("birthDate"),
                    }
                )
        return results

    def get_patient(self, patient_id: str) -> Optional[Dict[str, Any]]:
        data = self._read()
        for p in data["Patient"]:
            if p.get("id") == patient_id:
                return p
        return None

    def get_patient_history(self, patient_id: str) -> List[Dict[str, Any]]:
        data = self._read()
        history: List[Dict[str, Any]] = []
        ref = f"Patient/{patient_id}"
        for rt in (
            "Encounter",
            "Condition",
            "Observation",
            "MedicationStatement",
            "AllergyIntolerance",
            "ClinicalImpression",
        ):
            for r in data.get(rt, []):
                subject = (r.get("subject") or r.get("patient") or {}).get("reference")
                if subject == ref:
                    history.append(r)
        return history

    def commit_encounter(
        self,
        patient_id: str,
        payload: StructuredEncounterPayload,
        diagnosis_summary: Optional[str] = None,
    ) -> Dict[str, Any]:
        new_resources = build_resources_from_payload(
            patient_id=patient_id,
            payload=payload,
            diagnosis_summary=diagnosis_summary,
        )
        with self._lock:
            data = self._read()
            for r in new_resources:
                rt = r["resourceType"]
                data.setdefault(rt, []).append(r)
            self._write(data)
        return {
            "patient_id": patient_id,
            "resources_written": [
                {"resourceType": r["resourceType"], "id": r["id"]} for r in new_resources
            ],
        }


# -----------------------------------------------------------------------------
# Remote store (HAPI passthrough)
# -----------------------------------------------------------------------------

class RemoteFHIRStore:
    """Thin pass-through to an external FHIR server. Implements the same shape
    as ``LocalFHIRStore`` so it can be swapped in transparently.
    """

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")
        self._client = httpx.Client(
            base_url=self.base_url,
            headers={"Accept": "application/fhir+json"},
            timeout=30.0,
        )

    def search_patients(self, query: Optional[str] = None) -> List[Dict[str, Any]]:
        params = {"_count": "30"}
        if query:
            params["name"] = query
        r = self._client.get("/Patient", params=params)
        r.raise_for_status()
        bundle = r.json()
        return [
            {
                "id": e["resource"]["id"],
                "name": _patient_display_name(e["resource"]),
                "gender": e["resource"].get("gender"),
                "birthDate": e["resource"].get("birthDate"),
            }
            for e in bundle.get("entry", [])
        ]

    def get_patient(self, patient_id: str) -> Optional[Dict[str, Any]]:
        r = self._client.get(f"/Patient/{patient_id}")
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()

    def get_patient_history(self, patient_id: str) -> List[Dict[str, Any]]:
        history: List[Dict[str, Any]] = []
        for rt in (
            "Encounter",
            "Condition",
            "Observation",
            "MedicationStatement",
            "AllergyIntolerance",
            "ClinicalImpression",
        ):
            field = "patient" if rt == "AllergyIntolerance" else "subject"
            r = self._client.get(f"/{rt}", params={field: f"Patient/{patient_id}"})
            if r.status_code == 200:
                bundle = r.json()
                history.extend(e["resource"] for e in bundle.get("entry", []))
        return history

    def commit_encounter(
        self,
        patient_id: str,
        payload: StructuredEncounterPayload,
        diagnosis_summary: Optional[str] = None,
    ) -> Dict[str, Any]:
        new_resources = build_resources_from_payload(
            patient_id=patient_id,
            payload=payload,
            diagnosis_summary=diagnosis_summary,
        )
        bundle = {
            "resourceType": "Bundle",
            "type": "transaction",
            "entry": [
                {
                    "resource": r,
                    "request": {"method": "POST", "url": r["resourceType"]},
                }
                for r in new_resources
            ],
        }
        r = self._client.post("/", json=bundle)
        r.raise_for_status()
        return {
            "patient_id": patient_id,
            "resources_written": [
                {"resourceType": r["resourceType"], "id": r["id"]} for r in new_resources
            ],
            "remote_response": r.json(),
        }


# -----------------------------------------------------------------------------
# Factory
# -----------------------------------------------------------------------------

_store_instance: Optional[FHIRStore] = None
_store_lock = threading.Lock()


def get_store() -> FHIRStore:
    global _store_instance
    if _store_instance is not None:
        return _store_instance
    with _store_lock:
        if _store_instance is not None:
            return _store_instance
        settings = get_settings()
        if settings.fhir_mode == "remote":
            _store_instance = RemoteFHIRStore(settings.fhir_base_url)
        else:
            _store_instance = LocalFHIRStore(
                store_path=settings.patients_store_path,
                seed_bundle=settings.seed_bundle_path,
            )
    return _store_instance
