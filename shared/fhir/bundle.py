"""FHIR R4 resource assembly.

Translates the structurer's narrow Pydantic payload into a list of FHIR R4
resources ready to be wrapped in a transaction Bundle and POSTed.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from shared.fhir.schemas import StructuredEncounterPayload


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return str(uuid.uuid4())


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
