"""MCP server exposing patient-history tools to the diagnosis agent.

Two ways to use it:

1. **As a real MCP server over stdio** — run ``python -m backend.mcp_server.patient_mcp``.
   The diagnosis agent connects via the MCP stdio transport. This is the
   "production-shaped" path.

2. **As an in-process tool registry** — import :func:`get_local_tool_specs`
   and :func:`call_local_tool`. The orchestrator uses this path by default so
   the demo stays a single Python process and we avoid spawning subprocesses
   for each request. Both paths share the same tool implementations below, so
   behavior is identical either way.
"""

from __future__ import annotations

import json
import sys
from typing import Any, Callable, Dict, List, Optional

from backend.fhir.store import get_store


# -----------------------------------------------------------------------------
# Tool implementations (single source of truth)
# -----------------------------------------------------------------------------

def _search_patients(query: Optional[str] = None) -> Dict[str, Any]:
    """Find patients by partial name or id match."""
    return {"results": get_store().search_patients(query)}


def _get_patient(patient_id: str) -> Dict[str, Any]:
    """Return the full FHIR Patient resource (demographics, contact, identifiers)."""
    patient = get_store().get_patient(patient_id)
    if not patient:
        return {"error": f"Patient {patient_id} not found"}
    return patient


def _get_patient_history(patient_id: str) -> Dict[str, Any]:
    """Return all encounters, conditions, observations, medications, allergies,
    and clinical impressions on file for the given patient."""
    history = get_store().get_patient_history(patient_id)
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for r in history:
        grouped.setdefault(r["resourceType"], []).append(r)
    return {"patient_id": patient_id, "history": grouped, "total": len(history)}


TOOL_REGISTRY: Dict[str, Dict[str, Any]] = {
    "search_patients": {
        "fn": _search_patients,
        "description": "Search for patients by name or id. Returns a list of "
        "matches with id, name, gender, birthDate.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Partial name or id. Empty returns all patients.",
                }
            },
            "required": [],
        },
    },
    "get_patient": {
        "fn": _get_patient,
        "description": "Get the full FHIR Patient resource (demographics, "
        "identifiers, contact info) by patient id.",
        "input_schema": {
            "type": "object",
            "properties": {"patient_id": {"type": "string"}},
            "required": ["patient_id"],
        },
    },
    "get_patient_history": {
        "fn": _get_patient_history,
        "description": "Get the patient's full clinical history: encounters, "
        "conditions, observations, medications, allergies, clinical impressions. "
        "Use this before suggesting a diagnosis.",
        "input_schema": {
            "type": "object",
            "properties": {"patient_id": {"type": "string"}},
            "required": ["patient_id"],
        },
    },
}


# -----------------------------------------------------------------------------
# In-process API used by the diagnosis agent
# -----------------------------------------------------------------------------

def get_local_tool_specs() -> List[Dict[str, Any]]:
    """Return Anthropic-style tool specs (name/description/input_schema)."""
    return [
        {
            "name": name,
            "description": meta["description"],
            "input_schema": meta["input_schema"],
        }
        for name, meta in TOOL_REGISTRY.items()
    ]


def call_local_tool(name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    if name not in TOOL_REGISTRY:
        return {"error": f"Unknown tool: {name}"}
    fn: Callable[..., Dict[str, Any]] = TOOL_REGISTRY[name]["fn"]
    try:
        return fn(**(arguments or {}))
    except TypeError as exc:
        return {"error": f"Bad arguments for {name}: {exc}"}
    except Exception as exc:  # noqa: BLE001 - surface details to the agent
        return {"error": f"{type(exc).__name__}: {exc}"}


# -----------------------------------------------------------------------------
# Stdio MCP server (optional path)
# -----------------------------------------------------------------------------

def _run_stdio_server() -> None:
    """Run a real MCP server over stdio. Imported lazily so the rest of the app
    doesn't depend on the MCP SDK at import time."""

    from mcp.server import Server  # type: ignore
    from mcp.server.stdio import stdio_server  # type: ignore
    from mcp import types as mcp_types  # type: ignore
    import anyio

    server: Server = Server("promptopinion-patient-mcp")

    @server.list_tools()
    async def list_tools() -> List[mcp_types.Tool]:
        return [
            mcp_types.Tool(
                name=name,
                description=meta["description"],
                inputSchema=meta["input_schema"],
            )
            for name, meta in TOOL_REGISTRY.items()
        ]

    @server.call_tool()
    async def call_tool(
        name: str, arguments: Dict[str, Any]
    ) -> List[mcp_types.TextContent]:
        result = call_local_tool(name, arguments or {})
        return [mcp_types.TextContent(type="text", text=json.dumps(result))]

    async def main() -> None:
        async with stdio_server() as (read_stream, write_stream):
            await server.run(
                read_stream,
                write_stream,
                server.create_initialization_options(),
            )

    anyio.run(main)


if __name__ == "__main__":
    try:
        _run_stdio_server()
    except KeyboardInterrupt:
        sys.exit(0)
