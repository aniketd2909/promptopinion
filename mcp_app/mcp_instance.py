"""Construct the FastMCP server, declare SHARP capabilities, and register tools.

The capability advertisement (``ai.promptopinion/fhir-context``) tells the
Prompt Opinion platform which SMART scopes this server needs so the workspace
admin can grant them. Each tool registered below is an MCP-callable function
the platform's LLM can choose to invoke.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from mcp_app.mcp_constants import FHIR_CONTEXT_EXTENSION_KEY
from mcp_app.tools.active_conditions_tool import get_active_conditions
from mcp_app.tools.add_allergy_tool import add_allergy
from mcp_app.tools.add_condition_tool import add_condition
from mcp_app.tools.allergies_tool import get_allergies
from mcp_app.tools.commit_encounter_tool import commit_encounter
from mcp_app.tools.create_patient_tool import create_patient
from mcp_app.tools.encounter_history_tool import get_encounter_history
from mcp_app.tools.find_patient_tool import find_patient
from mcp_app.tools.get_patient_tool import get_patient
from mcp_app.tools.immunizations_tool import get_immunizations
from mcp_app.tools.medications_tool import get_medications
from mcp_app.tools.patient_history_tool import get_patient_history
from mcp_app.tools.recent_observations_tool import get_recent_observations
from mcp_app.tools.record_observation_tool import record_observation
from mcp_app.tools.schedule_appointment_tool import schedule_appointment
from mcp_app.tools.structure_conversation_tool import structure_clinical_conversation
from mcp_app.tools.suggest_diagnosis_tool import suggest_diagnosis
from mcp_app.tools.update_patient_tool import update_patient_demographics


mcp = FastMCP("PromptOpinion Clinical Scribe", stateless_http=True, host="0.0.0.0")


# Patch capabilities to advertise the FHIR-context extension and SMART scopes
# the platform will provision. This is the SHARP-on-MCP convention.
_original_get_capabilities = mcp._mcp_server.get_capabilities


def _patched_get_capabilities(notification_options, experimental_capabilities):
    caps = _original_get_capabilities(notification_options, experimental_capabilities)
    caps.model_extra["extensions"] = {
        FHIR_CONTEXT_EXTENSION_KEY: {
            "scopes": [
                # Read scopes
                {"name": "patient/Patient.rs", "required": True},
                {"name": "patient/Encounter.rs", "required": True},
                {"name": "patient/Observation.rs", "required": True},
                {"name": "patient/Condition.rs", "required": True},
                {"name": "patient/MedicationStatement.rs"},
                {"name": "patient/MedicationRequest.rs"},
                {"name": "patient/AllergyIntolerance.rs"},
                {"name": "patient/Immunization.rs"},
                {"name": "patient/Appointment.rs"},
                # Write scopes
                {"name": "patient/Patient.cu"},
                {"name": "patient/Encounter.cu"},
                {"name": "patient/Observation.cu"},
                {"name": "patient/Condition.cu"},
                {"name": "patient/AllergyIntolerance.cu"},
                {"name": "patient/Appointment.cu"},
                {"name": "patient/ClinicalImpression.cu"},
            ]
        }
    }
    return caps


mcp._mcp_server.get_capabilities = _patched_get_capabilities


# ── Read tools ───────────────────────────────────────────────────────────────

mcp.tool(
    name="FindPatient",
    description=(
        "Search the connected FHIR server for a patient. Search fields map "
        "directly to the FHIR R4 Patient search params (name, given/firstName, "
        "family/lastName, birthdate, gender, identifier). Provide as many as "
        "needed to narrow the result. Returns the patient's FHIR id when one "
        "match is found, or a list of candidates when multiple match."
    ),
)(find_patient)

mcp.tool(
    name="GetPatient",
    description=(
        "Get a patient's demographics (name, DOB, gender, contacts, address) "
        "by FHIR id. Use after FindPatient resolves an id."
    ),
)(get_patient)

mcp.tool(
    name="GetPatientHistory",
    description=(
        "Get the patient's full clinical history: encounters, conditions, "
        "observations, medications, allergies, and clinical impressions. "
        "Use this before suggesting a diagnosis."
    ),
)(get_patient_history)

mcp.tool(
    name="GetActiveConditions",
    description=(
        "Search FHIR Condition for the patient's problem list. Maps to FHIR R4 "
        "Condition?subject=…&clinical-status=…&category=…&code=…&severity=…&"
        "recorded-date=… (defaults to clinical-status=active, sorted by "
        "recorded-date desc)."
    ),
)(get_active_conditions)

mcp.tool(
    name="GetMedications",
    description=(
        "Search FHIR for the patient's medications across MedicationStatement "
        "(taken) and MedicationRequest (prescribed). Maps to FHIR R4 search "
        "with subject, status (default 'active'), and code filters."
    ),
)(get_medications)

mcp.tool(
    name="GetAllergies",
    description=(
        "Search FHIR AllergyIntolerance for the patient. Maps to FHIR R4 "
        "AllergyIntolerance?patient=…&clinical-status=…&category=…&"
        "criticality=…&type=…&code=…."
    ),
)(get_allergies)

mcp.tool(
    name="GetRecentObservations",
    description=(
        "Search FHIR Observation (vitals, labs, exams). Maps to FHIR R4 "
        "Observation?subject=…&category=…&code=…&status=…&date=… (sorted by "
        "date desc, default status='final,amended')."
    ),
)(get_recent_observations)

mcp.tool(
    name="GetEncounterHistory",
    description=(
        "Search FHIR Encounter for the patient's visits. Maps to FHIR R4 "
        "Encounter?subject=…&status=…&class=…&type=…&date=…&reason-code=… "
        "(sorted by date desc)."
    ),
)(get_encounter_history)

mcp.tool(
    name="GetImmunizations",
    description=(
        "Search FHIR Immunization for the patient. Maps to FHIR R4 "
        "Immunization?patient=…&status=…&vaccine-code=…&date=… (sorted by "
        "date desc)."
    ),
)(get_immunizations)


# ── AI tools ─────────────────────────────────────────────────────────────────

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


# ── Write tools ──────────────────────────────────────────────────────────────

mcp.tool(
    name="CreatePatient",
    description=(
        "Register a new patient on the FHIR server. Requires firstName + "
        "lastName; birthDate, gender, phone, email are optional. Returns the "
        "new FHIR Patient id."
    ),
)(create_patient)

mcp.tool(
    name="UpdatePatientDemographics",
    description=(
        "Update an existing patient's name, DOB, gender, phone, or email. "
        "Only provided fields are changed; others are preserved."
    ),
)(update_patient_demographics)

mcp.tool(
    name="RecordObservation",
    description=(
        "Record a single observation — vital sign, lab result, or similar — "
        "on the patient's chart. Numeric values are stored as Quantity, "
        "non-numeric as String."
    ),
)(record_observation)

mcp.tool(
    name="AddCondition",
    description=(
        "Add a diagnosis / condition to the patient's problem list."
    ),
)(add_condition)

mcp.tool(
    name="AddAllergy",
    description=(
        "Record a new allergy / intolerance on the patient's chart."
    ),
)(add_allergy)

mcp.tool(
    name="ScheduleAppointment",
    description=(
        "Book a future appointment for the patient. Requires ISO 8601 start "
        "and end times. Returns the new FHIR Appointment id."
    ),
)(schedule_appointment)

mcp.tool(
    name="CommitEncounter",
    description=(
        "Persist an approved structured visit to the connected FHIR server as "
        "a transaction Bundle (Encounter + Observations + Conditions + "
        "MedicationStatements + AllergyIntolerances + ClinicalImpression)."
    ),
)(commit_encounter)
