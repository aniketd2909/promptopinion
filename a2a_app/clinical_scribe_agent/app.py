"""A2A application for the clinical_scribe_agent.

Run::

    uvicorn a2a_app.clinical_scribe_agent.app:a2a_app --host 0.0.0.0 --port 8020

The agent card is published at /.well-known/agent-card.json. All other
endpoints require an X-API-Key header (configure via API_KEYS / API_KEY_PRIMARY).
"""

import os

from dotenv import load_dotenv
load_dotenv()

from a2a.types import AgentSkill

from a2a_app.shared.app_factory import create_a2a_app

from .agent import root_agent


_url = os.getenv("CLINICAL_SCRIBE_AGENT_URL", os.getenv("BASE_URL", "http://localhost:8020"))
_platform_base = os.getenv("PO_PLATFORM_BASE_URL", "http://localhost:5139")


a2a_app = create_a2a_app(
    agent=root_agent,
    name="clinical_scribe_agent",
    description=(
        "Clinical scribe assistant. Structures a doctor-patient conversation "
        "into FHIR-shaped data, fetches the patient's history, suggests a "
        "differential and next steps, and writes the approved encounter back "
        "to the FHIR server as a transaction Bundle."
    ),
    url=_url,
    port=int(os.getenv("CLINICAL_SCRIBE_AGENT_PORT", "8020")),
    fhir_extension_uri=f"{_platform_base}/schemas/a2a/v1/fhir-context",
    fhir_scopes=[
        # Read scopes — used while structuring + suggesting diagnosis.
        {"name": "patient/Patient.rs", "required": True},
        {"name": "patient/Encounter.rs", "required": True},
        {"name": "patient/Condition.rs", "required": True},
        {"name": "patient/Observation.rs", "required": True},
        {"name": "patient/MedicationRequest.rs", "required": True},
        {"name": "patient/MedicationStatement.rs"},
        {"name": "patient/AllergyIntolerance.rs"},
        # Write scopes — used by commit_encounter.
        {"name": "patient/Encounter.cu", "required": True},
        {"name": "patient/Condition.cu", "required": True},
        {"name": "patient/Observation.cu", "required": True},
        {"name": "patient/ClinicalImpression.cu"},
    ],
    skills=[
        AgentSkill(
            id="structure-conversation",
            name="structure-conversation",
            description=(
                "Convert a doctor-patient transcript into a structured "
                "FHIR-shaped visit payload."
            ),
            tags=["scribe", "fhir", "structured-output"],
        ),
        AgentSkill(
            id="patient-demographics",
            name="patient-demographics",
            description="Retrieve the active patient's name, DOB, and contacts.",
            tags=["demographics", "fhir"],
        ),
        AgentSkill(
            id="active-conditions",
            name="active-conditions",
            description="Get the patient's current active conditions / problem list.",
            tags=["conditions", "fhir"],
        ),
        AgentSkill(
            id="active-medications",
            name="active-medications",
            description="Get the patient's current and prescribed medications.",
            tags=["medications", "fhir"],
        ),
        AgentSkill(
            id="recent-observations",
            name="recent-observations",
            description="Retrieve recent vitals, lab results, and observations.",
            tags=["observations", "fhir"],
        ),
        AgentSkill(
            id="allergies",
            name="allergies",
            description="Retrieve recorded allergies for the active patient.",
            tags=["allergies", "fhir"],
        ),
        AgentSkill(
            id="commit-encounter",
            name="commit-encounter",
            description=(
                "Persist a doctor-approved structured visit to the FHIR server "
                "as a transaction Bundle."
            ),
            tags=["scribe", "fhir", "write"],
        ),
    ],
)
