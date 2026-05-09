"""Diagnosis agent — Claude Opus 4.7 with MCP-backed patient history tools.

Why direct Anthropic SDK and not LangChain tool calling?
- We want a clean **tool-use loop driven by MCP tools**: the agent decides
  when to fetch history vs. ask for more info, and we want full visibility
  over which tool calls happened (so the UI can show "agent looked up: X
  conditions, Y observations").
- LangChain's tool agents work but add an indirection that hides the loop.
  For a demo where the agent's reasoning is the product, the raw loop reads
  better.

The tools are sourced from the MCP registry in :mod:`backend.mcp_server.patient_mcp`
so the *same* tool definitions that an external MCP stdio client would see
are the ones the agent uses in-process.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import anthropic

from backend.config import get_settings
from backend.fhir.schemas import DiagnosisSuggestion, StructuredEncounterPayload
from backend.mcp_server.patient_mcp import call_local_tool, get_local_tool_specs


SYSTEM_PROMPT = """\
You are a clinical decision-support assistant helping a physician triage a
patient encounter. You will receive:

1. A structured summary of the *current* visit (chief complaint, vitals,
   symptoms, conditions discussed, medications mentioned, allergies).
2. A patient_id you can use with the available MCP tools to fetch the
   patient's prior FHIR record (encounters, conditions, observations,
   medications, allergies, prior clinical impressions).

Your job:
- Call the MCP tool `get_patient_history` once with the given patient_id to
  retrieve prior context. If the result is large, scan it for the few items
  most relevant to today's complaint — chronic conditions, prior episodes of
  similar symptoms, contraindicated meds, allergies that interact with the
  likely treatment.
- After you have enough context, produce a final JSON object matching this
  exact schema (no extra keys, no prose around it):

{
  "differential": [string, ...],
  "recommended_next_steps": [
    {"title": string, "rationale": string, "priority": "urgent"|"routine"|"optional"},
    ...
  ],
  "red_flags": [string, ...],
  "history_signals_used": [string, ...],
  "summary": string
}

Rules:
- `differential` is ranked most-likely first.
- `red_flags` are items the physician absolutely must not miss given history.
- `history_signals_used` lists specific items from the prior record that
  influenced the suggestion. Empty list if no history was retrieved.
- `summary` is one paragraph the physician can read in 10 seconds.
- Do NOT prescribe — recommend evaluations, referrals, follow-up tests.
- If you have insufficient information to suggest *anything*, return the
  schema with empty arrays and a `summary` explaining what's missing.

When you are ready to deliver the final answer, respond with the JSON object
ONLY. No code fences, no commentary.
"""


@dataclass
class DiagnosisRun:
    suggestion: DiagnosisSuggestion
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    raw_text: str = ""


_client: Optional[anthropic.Anthropic] = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=get_settings().anthropic_api_key)
    return _client


def _user_prompt(payload: StructuredEncounterPayload, patient_id: str) -> str:
    return (
        f"patient_id: {patient_id}\n\n"
        f"Today's visit (structured):\n{payload.model_dump_json(indent=2)}\n\n"
        "Use `get_patient_history` for context, then respond with the final "
        "JSON suggestion."
    )


def _extract_json_object(text: str) -> Dict[str, Any]:
    text = text.strip()
    # Tolerate accidental code fences.
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    # Clip from first '{' to matching last '}'.
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError(f"No JSON object found in model output: {text!r}")
    return json.loads(text[start : end + 1])


def suggest_diagnosis(
    payload: StructuredEncounterPayload,
    patient_id: str,
    max_tool_iterations: int = 4,
) -> DiagnosisRun:
    settings = get_settings()
    if not settings.anthropic_api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. Add it to App/.env to enable the diagnosis agent."
        )

    tools = get_local_tool_specs()
    messages: List[Dict[str, Any]] = [
        {"role": "user", "content": _user_prompt(payload, patient_id)}
    ]

    tool_calls_log: List[Dict[str, Any]] = []
    final_text = ""

    for _ in range(max_tool_iterations):
        response = _get_client().messages.create(
            model=settings.diagnosis_model,
            max_tokens=2048,
            system=SYSTEM_PROMPT,
            tools=tools,
            messages=messages,
        )

        if response.stop_reason == "tool_use":
            assistant_blocks: List[Dict[str, Any]] = []
            tool_results: List[Dict[str, Any]] = []
            for block in response.content:
                if block.type == "text":
                    assistant_blocks.append({"type": "text", "text": block.text})
                elif block.type == "tool_use":
                    assistant_blocks.append(
                        {
                            "type": "tool_use",
                            "id": block.id,
                            "name": block.name,
                            "input": block.input,
                        }
                    )
                    tool_output = call_local_tool(block.name, block.input or {})
                    tool_calls_log.append(
                        {"name": block.name, "input": block.input, "output": tool_output}
                    )
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": json.dumps(tool_output)[:80_000],
                        }
                    )
            messages.append({"role": "assistant", "content": assistant_blocks})
            messages.append({"role": "user", "content": tool_results})
            continue

        # End of turn — collect text.
        final_text = "".join(b.text for b in response.content if b.type == "text")
        break

    if not final_text:
        raise RuntimeError(
            "Diagnosis agent did not produce a final answer within the tool-use budget."
        )

    parsed = _extract_json_object(final_text)
    suggestion = DiagnosisSuggestion.model_validate(parsed)
    return DiagnosisRun(
        suggestion=suggestion,
        tool_calls=tool_calls_log,
        raw_text=final_text,
    )
