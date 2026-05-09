"""LangGraph orchestrator for the encounter pipeline.

Nodes (each is an A2A "agent" with a focused responsibility):

    transcribe -> structure -> diagnose -> [HITL pause] -> persist

The graph supports two entry points:
- ``run_audio_pipeline(audio_bytes, filename, patient_id)`` — start from audio.
- ``run_text_pipeline(transcript, patient_id)`` — start from a transcript
  (e.g. a doctor pasted notes, or an upload was already transcribed).

The "doctor approves/edits" step is *outside* the graph: we run the graph up
to and including diagnosis, return the structured + diagnosis output to the
UI, and persist on a separate explicit call (``persist_after_approval``). This
matches the flowchart's bidirectional Voice2Text <-> Structure arrow and the
downstream approval gate.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Dict, List, Optional, TypedDict

from langgraph.graph import END, StateGraph

from backend.agents.diagnosis import DiagnosisRun, suggest_diagnosis
from backend.agents.fhir_structurer import structure_transcript
from backend.agents.transcriber import TranscriptionResult, transcribe_audio
from backend.fhir.schemas import DiagnosisSuggestion, StructuredEncounterPayload
from backend.fhir.store import get_store


class EncounterState(TypedDict, total=False):
    # Inputs
    audio_bytes: Optional[bytes]
    audio_filename: Optional[str]
    transcript: Optional[str]
    patient_id: Optional[str]
    additional_context: Optional[str]

    # Intermediate / outputs
    transcription: Dict[str, Any]
    structured: Dict[str, Any]
    diagnosis: Dict[str, Any]
    diagnosis_tool_calls: List[Dict[str, Any]]
    errors: List[str]


# -----------------------------------------------------------------------------
# Nodes — each represents an A2A agent
# -----------------------------------------------------------------------------

def transcribe_node(state: EncounterState) -> EncounterState:
    audio_bytes = state.get("audio_bytes")
    if not audio_bytes:
        # Already have a transcript — pass through.
        return {}
    result: TranscriptionResult = transcribe_audio(
        audio_bytes,
        filename=state.get("audio_filename") or "audio.webm",
    )
    return {
        "transcript": result.text,
        "transcription": {
            "text": result.text,
            "language": result.language,
            "duration_sec": result.duration_sec,
        },
    }


def structure_node(state: EncounterState) -> EncounterState:
    transcript = state.get("transcript")
    if not transcript:
        return {"errors": ["structure_node: no transcript to structure"]}
    payload: StructuredEncounterPayload = structure_transcript(
        transcript=transcript,
        additional_context=state.get("additional_context"),
    )
    if state.get("patient_id"):
        payload.patient_id = state["patient_id"]
    return {"structured": payload.model_dump()}


def diagnose_node(state: EncounterState) -> EncounterState:
    structured = state.get("structured")
    patient_id = state.get("patient_id")
    if not structured:
        return {"errors": ["diagnose_node: missing structured payload"]}
    if not patient_id:
        # Without a patient_id, the agent has no history to fetch, but it can
        # still produce a baseline differential. We pass a sentinel id and the
        # MCP tool will return "Patient not found" — the agent then proceeds
        # with empty history.
        patient_id = "__unknown__"
    payload = StructuredEncounterPayload.model_validate(structured)
    run: DiagnosisRun = suggest_diagnosis(payload=payload, patient_id=patient_id)
    return {
        "diagnosis": run.suggestion.model_dump(),
        "diagnosis_tool_calls": run.tool_calls,
    }


# -----------------------------------------------------------------------------
# Graph factory
# -----------------------------------------------------------------------------

def _build_graph():
    g = StateGraph(EncounterState)
    g.add_node("transcribe", transcribe_node)
    g.add_node("structure", structure_node)
    g.add_node("diagnose", diagnose_node)
    g.set_entry_point("transcribe")
    g.add_edge("transcribe", "structure")
    g.add_edge("structure", "diagnose")
    g.add_edge("diagnose", END)
    return g.compile()


_compiled = None


def _get_compiled():
    global _compiled
    if _compiled is None:
        _compiled = _build_graph()
    return _compiled


# -----------------------------------------------------------------------------
# Public API
# -----------------------------------------------------------------------------

def run_audio_pipeline(
    audio_bytes: bytes,
    audio_filename: str,
    patient_id: Optional[str] = None,
    additional_context: Optional[str] = None,
) -> Dict[str, Any]:
    state: EncounterState = {
        "audio_bytes": audio_bytes,
        "audio_filename": audio_filename,
        "patient_id": patient_id,
        "additional_context": additional_context,
    }
    final = _get_compiled().invoke(state)
    return _serialize_state(final)


def run_text_pipeline(
    transcript: str,
    patient_id: Optional[str] = None,
    additional_context: Optional[str] = None,
) -> Dict[str, Any]:
    state: EncounterState = {
        "transcript": transcript,
        "patient_id": patient_id,
        "additional_context": additional_context,
    }
    final = _get_compiled().invoke(state)
    return _serialize_state(final)


def persist_after_approval(
    patient_id: str,
    approved_payload: Dict[str, Any],
    diagnosis_summary: Optional[str] = None,
) -> Dict[str, Any]:
    """Doctor has reviewed/edited the structured output. Write to the FHIR store."""
    payload = StructuredEncounterPayload.model_validate(approved_payload)
    return get_store().commit_encounter(
        patient_id=patient_id,
        payload=payload,
        diagnosis_summary=diagnosis_summary,
    )


def _serialize_state(state: EncounterState) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "transcript": state.get("transcript"),
        "transcription": state.get("transcription"),
        "structured": state.get("structured"),
        "diagnosis": state.get("diagnosis"),
        "diagnosis_tool_calls": state.get("diagnosis_tool_calls", []),
        "errors": state.get("errors", []),
        "patient_id": state.get("patient_id"),
    }
    return out
