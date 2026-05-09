"""Pydantic schemas the structuring agent emits.

These are deliberately a *narrow, opinionated* slice of FHIR R4 — just the
fields a clinical encounter conversation typically yields. The structurer is
prompted to emit JSON matching this shape; we then assemble those into a real
FHIR transaction Bundle on the way to the store.
"""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class CodingHint(BaseModel):
    """A loose code suggestion. The model is not expected to know real SNOMED /
    LOINC codes off the top of its head; `display` is the source of truth and
    `system` / `code` are filled when the model is confident."""

    system: Optional[str] = None
    code: Optional[str] = None
    display: str


class StructuredObservation(BaseModel):
    """Vital signs, lab values, symptoms reported."""

    kind: str = Field(
        description="Free-text label, e.g. 'Blood pressure', 'Cough', 'Fatigue'."
    )
    value: Optional[str] = Field(
        default=None,
        description="Measured or reported value as written, e.g. '140/90 mmHg', "
        "'present', '101.2 F'.",
    )
    coding: Optional[CodingHint] = None
    note: Optional[str] = None


class StructuredCondition(BaseModel):
    """A diagnosis, problem, or symptom-level condition mentioned."""

    name: str
    clinical_status: str = Field(
        default="active",
        description="One of: active | recurrence | relapse | inactive | "
        "remission | resolved.",
    )
    onset: Optional[str] = Field(
        default=None,
        description="Free-text onset description as the patient stated it, "
        "e.g. 'three days ago'.",
    )
    coding: Optional[CodingHint] = None
    note: Optional[str] = None


class StructuredMedication(BaseModel):
    """A medication the patient is currently taking or was just prescribed."""

    name: str
    status: str = Field(
        default="active",
        description="active | completed | stopped | on-hold | intended.",
    )
    dosage: Optional[str] = None
    coding: Optional[CodingHint] = None


class StructuredAllergy(BaseModel):
    substance: str
    reaction: Optional[str] = None
    severity: Optional[str] = None  # mild | moderate | severe


class StructuredEncounter(BaseModel):
    """The visit itself."""

    reason: str = Field(description="Chief complaint / reason for the visit.")
    summary: str = Field(description="Two- or three-sentence clinical summary.")
    encounter_class: str = Field(
        default="AMB",
        description="FHIR v3 ActCode: AMB (ambulatory) | EMER | IMP | HH | VR.",
    )


class StructuredEncounterPayload(BaseModel):
    """Top-level object the structuring LLM returns."""

    patient_id: Optional[str] = Field(
        default=None,
        description="If the conversation references an existing patient by id "
        "or is otherwise resolvable, the upstream agent fills this in. The "
        "structurer itself should leave it null.",
    )
    encounter: StructuredEncounter
    observations: List[StructuredObservation] = Field(default_factory=list)
    conditions: List[StructuredCondition] = Field(default_factory=list)
    medications: List[StructuredMedication] = Field(default_factory=list)
    allergies: List[StructuredAllergy] = Field(default_factory=list)


class DiagnosisStep(BaseModel):
    title: str
    rationale: str
    priority: str = Field(default="routine", description="urgent | routine | optional")


class DiagnosisSuggestion(BaseModel):
    """Output of the diagnosis agent."""

    differential: List[str] = Field(
        default_factory=list,
        description="Ranked list of plausible diagnoses to consider.",
    )
    recommended_next_steps: List[DiagnosisStep] = Field(default_factory=list)
    red_flags: List[str] = Field(
        default_factory=list,
        description="Anything the doctor must not miss given history + presentation.",
    )
    history_signals_used: List[str] = Field(
        default_factory=list,
        description="Specific items from the patient's prior record that influenced "
        "the suggestion. Empty if no history was retrieved.",
    )
    summary: str
