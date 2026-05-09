"""Clinical Scribe ADK agent.

Receives a doctor-patient encounter (transcript or summary) and helps the
clinician by:

  • reading the patient's FHIR record (demographics, conditions, meds,
    observations, allergies),
  • turning a transcript into a structured FHIR-shaped payload,
  • suggesting a differential and next steps grounded in the patient's history,
  • persisting the doctor-approved record back to FHIR as a transaction Bundle.

FHIR credentials arrive in the A2A message metadata under the
``fhir-context`` extension and are lifted into session state by
``extract_fhir_context`` before the model runs.
"""

from __future__ import annotations

import os

from google.adk.agents import Agent
from google.adk.models.lite_llm import LiteLlm

from a2a_app.shared.fhir_hook import extract_fhir_context
from a2a_app.shared.tools import (
    commit_encounter,
    get_active_conditions,
    get_active_medications,
    get_allergies,
    get_patient_demographics,
    get_recent_observations,
    structure_clinical_conversation,
)


_model_name = os.getenv(
    "CLINICAL_SCRIBE_AGENT_MODEL",
    os.getenv("HEALTHCARE_AGENT_MODEL", "gemini/gemini-3.1-flash-lite"),
)
_model = LiteLlm(model=_model_name)

INSTRUCTION = """\
You are a clinical scribe and decision-support assistant. You have read access
to the patient's FHIR record and the ability to convert a doctor-patient
conversation transcript into a structured visit, then write the
doctor-approved record back to FHIR.

Workflow you should follow when the doctor pastes a transcript:
  1. Call `structure_clinical_conversation` with the transcript to produce a
     structured visit payload (chief complaint, vitals, conditions, meds,
     allergies). Show the structured object back to the doctor.
  2. Use the FHIR query tools (`get_patient_demographics`,
     `get_active_conditions`, `get_active_medications`,
     `get_recent_observations`, `get_allergies`) to learn the patient's prior
     state.
  3. Suggest a ranked differential and recommended next steps grounded in
     today's findings *and* the prior history. Highlight red flags. Never
     invent FHIR data — if a tool returns nothing, say so.
  4. Wait for the doctor to confirm or edit the structured payload, then call
     `commit_encounter` with the approved JSON. Never call `commit_encounter`
     before the doctor approves.

If FHIR context is not present, explain that the caller must include the
fhir-context metadata. Do not hallucinate clinical data.
"""

root_agent = Agent(
    name="clinical_scribe_agent",
    model=_model,
    description=(
        "Clinical scribe assistant. Structures a doctor-patient conversation "
        "into FHIR-shaped data, suggests a differential and next steps using "
        "the patient's FHIR history, and writes the approved record back to "
        "the FHIR server."
    ),
    instruction=INSTRUCTION,
    tools=[
        structure_clinical_conversation,
        get_patient_demographics,
        get_active_conditions,
        get_active_medications,
        get_recent_observations,
        get_allergies,
        commit_encounter,
    ],
    before_model_callback=extract_fhir_context,
)
