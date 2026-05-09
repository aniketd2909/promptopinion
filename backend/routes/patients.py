from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from backend.fhir.store import get_store


router = APIRouter(prefix="/api/patients", tags=["patients"])


@router.get("")
def list_patients(q: Optional[str] = Query(default=None, description="Search by name or id")):
    return {"patients": get_store().search_patients(q)}


@router.get("/{patient_id}")
def get_patient(patient_id: str):
    patient = get_store().get_patient(patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail=f"Patient {patient_id} not found")
    return patient


@router.get("/{patient_id}/history")
def get_history(patient_id: str):
    if not get_store().get_patient(patient_id):
        raise HTTPException(status_code=404, detail=f"Patient {patient_id} not found")
    history = get_store().get_patient_history(patient_id)
    by_type = {}
    for r in history:
        by_type.setdefault(r["resourceType"], []).append(r)
    return {"patient_id": patient_id, "total": len(history), "by_type": by_type}
