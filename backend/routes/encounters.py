from typing import Any, Dict, Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from backend.agents.graph import (
    persist_after_approval,
    run_audio_pipeline,
    run_text_pipeline,
)
from backend.agents.transcriber import transcribe_audio


router = APIRouter(prefix="/api/encounters", tags=["encounters"])


# -----------------------------------------------------------------------------
# Step 1 (alone): just transcribe — useful when the UI wants to show the
# transcript before the slower structure+diagnose phase runs.
# -----------------------------------------------------------------------------

@router.post("/transcribe")
async def transcribe_only(audio: UploadFile = File(...)) -> Dict[str, Any]:
    audio_bytes = await audio.read()
    if not audio_bytes:
        raise HTTPException(status_code=400, detail="Empty audio upload")
    result = transcribe_audio(audio_bytes, filename=audio.filename or "audio.webm")
    return {
        "transcript": result.text,
        "language": result.language,
        "duration_sec": result.duration_sec,
    }


# -----------------------------------------------------------------------------
# Step 2: full pipeline from audio
# -----------------------------------------------------------------------------

@router.post("/analyze-audio")
async def analyze_audio(
    audio: UploadFile = File(...),
    patient_id: Optional[str] = Form(default=None),
    additional_context: Optional[str] = Form(default=None),
) -> Dict[str, Any]:
    audio_bytes = await audio.read()
    if not audio_bytes:
        raise HTTPException(status_code=400, detail="Empty audio upload")
    return run_audio_pipeline(
        audio_bytes=audio_bytes,
        audio_filename=audio.filename or "audio.webm",
        patient_id=patient_id,
        additional_context=additional_context,
    )


# -----------------------------------------------------------------------------
# Step 2 (alt): full pipeline from a transcript
# -----------------------------------------------------------------------------

class TextAnalyzeBody(BaseModel):
    transcript: str
    patient_id: Optional[str] = None
    additional_context: Optional[str] = None


@router.post("/analyze-text")
def analyze_text(body: TextAnalyzeBody) -> Dict[str, Any]:
    if not body.transcript.strip():
        raise HTTPException(status_code=400, detail="Empty transcript")
    return run_text_pipeline(
        transcript=body.transcript,
        patient_id=body.patient_id,
        additional_context=body.additional_context,
    )


# -----------------------------------------------------------------------------
# Step 3: doctor-approved persistence
# -----------------------------------------------------------------------------

class ApproveBody(BaseModel):
    patient_id: str
    approved_payload: Dict[str, Any]
    diagnosis_summary: Optional[str] = None


@router.post("/approve")
def approve(body: ApproveBody) -> Dict[str, Any]:
    return persist_after_approval(
        patient_id=body.patient_id,
        approved_payload=body.approved_payload,
        diagnosis_summary=body.diagnosis_summary,
    )
