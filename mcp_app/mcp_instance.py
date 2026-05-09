"""Construct the FastMCP server, declare SHARP capabilities, and register tools.

The capability advertisement (``ai.promptopinion/fhir-context``) tells the
Prompt Opinion platform which SMART scopes this server needs so the workspace
admin can grant them. Each tool registered below is an MCP-callable function
the platform's LLM can choose to invoke.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from mcp_app.mcp_constants import FHIR_CONTEXT_EXTENSION_KEY
from mcp_app.tools.commit_encounter_tool import commit_encounter
from mcp_app.tools.find_patient_tool import find_patient
from mcp_app.tools.patient_history_tool import get_patient_history
from mcp_app.tools.structure_conversation_tool import structure_clinical_conversation
from mcp_app.tools.suggest_diagnosis_tool import suggest_diagnosis


mcp = FastMCP("PromptOpinion Clinical Scribe", stateless_http=True, host="0.0.0.0")


# Patch capabilities to advertise the FHIR-context extension and SMART scopes
# the platform will provision. This is the SHARP-on-MCP convention.
_original_get_capabilities = mcp._mcp_server.get_capabilities


def _patched_get_capabilities(notification_options, experimental_capabilities):
    caps = _original_get_capabilities(notification_options, experimental_capabilities)
    caps.model_extra["extensions"] = {
        FHIR_CONTEXT_EXTENSION_KEY: {
            "scopes": [
                {"name": "patient/Patient.rs", "required": True},
                {"name": "patient/Encounter.rs", "required": True},
                {"name": "patient/Observation.rs", "required": True},
                {"name": "patient/Condition.rs", "required": True},
                {"name": "patient/MedicationStatement.rs"},
                {"name": "patient/AllergyIntolerance.rs"},
                # Write scopes for CommitEncounter
                {"name": "patient/Encounter.cu"},
                {"name": "patient/Observation.cu"},
                {"name": "patient/Condition.cu"},
                {"name": "patient/ClinicalImpression.cu"},
            ]
        }
    }
    return caps


mcp._mcp_server.get_capabilities = _patched_get_capabilities


# Tool registrations — names use PascalCase by convention (matches reference impl).
mcp.tool(
    name="FindPatient",
    description=(
        "Search the connected FHIR server for a patient by first / last name. "
        "Returns the patient's FHIR id when exactly one match is found."
    ),
)(find_patient)

mcp.tool(
    name="GetPatientHistory",
    description=(
        "Get the patient's full clinical history: encounters, conditions, "
        "observations, medications, allergies, and clinical impressions. "
        "Use this before suggesting a diagnosis."
    ),
)(get_patient_history)

mcp.tool(
    name="StructureClinicalConversation",
    description=(
        "Take the transcript of a doctor-patient conversation and convert it "
        "to a structured clinical payload (chief complaint, vitals, conditions, "
        "medications, allergies) ready for FHIR persistence."
    ),
)(structure_clinical_conversation)

mcp.tool(
    name="SuggestDiagnosis",
    description=(
        "Given a structured visit payload and the patient's id, fetch the "
        "patient's history and produce a ranked differential, recommended next "
        "steps, and red flags. Use after StructureClinicalConversation."
    ),
)(suggest_diagnosis)

mcp.tool(
    name="CommitEncounter",
    description=(
        "Persist an approved structured visit to the connected FHIR server as "
        "a transaction Bundle (Encounter + Observations + Conditions + "
        "MedicationStatements + AllergyIntolerances + ClinicalImpression)."
    ),
)(commit_encounter)
