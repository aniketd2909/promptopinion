# PromptOpinion Clinical Scribe

A clinical-scribe AI for the Prompt Opinion platform. Structures a
doctor-patient conversation into FHIR resources, fetches the patient's prior
history, suggests diagnostic next steps, and writes the doctor-approved
encounter back to FHIR.

The project ships **two publishable artifacts** that share a small clinical
helper library:

| | What | Path | Run on |
|---|---|---|---|
| 🟦 | **MCP server** (publish to Marketplace) | [mcp_app/](mcp_app/) | port 8010 |
| 🟪 | **A2A agent** (publish to Marketplace) | [a2a_app/](a2a_app/) | port 8020 |
| ⚙️  | Shared FHIR helpers (schemas, bundle assembly, structuring agent) | [shared/](shared/) | imported |

In production the MCP server and A2A agent run on their own infrastructure and
the platform injects FHIR context per request.

## Architecture

```
                            Prompt Opinion platform LLM
                              │           │
                              │ HTTP+headers (SHARP)        A2A JSON-RPC
                              │  x-fhir-server-url           params.message.metadata
                              │  x-fhir-access-token            "fhir-context": {...}
                              │  x-patient-id                X-API-Key
                              ▼           ▼
                    ┌────────────────┐  ┌──────────────────────┐
                    │  MCP server    │  │  A2A agent (ADK)     │
                    │  mcp_app/      │  │  a2a_app/            │
                    │  port 8010     │  │  port 8020           │
                    │                │  │                      │
                    │  Tools:        │  │  ADK tools:          │
                    │  • FindPatient │  │  • get_patient_*     │
                    │  • GetPatient  │  │  • get_active_*      │
                    │    History     │  │  • structure_…       │
                    │  • Structure…  │  │  • commit_encounter  │
                    │  • SuggestDx   │  │                      │
                    │  • CommitEnc   │  │  Hook:               │
                    │                │  │  before_model_       │
                    │  Capability:   │  │    callback =        │
                    │   ai.prompt    │  │    extract_fhir_     │
                    │   opinion/     │  │    context           │
                    │   fhir-context │  │                      │
                    │   + scopes     │  │                      │
                    └───────┬────────┘  └─────────┬────────────┘
                            │                     │
                            │  shared/ (schemas, bundle, structurer)
                            │                     │
                            └──────────┬──────────┘
                                       │
                                       ▼  HTTP FHIR R4
                          ┌──────────────────────────────┐
                          │       FHIR R4 server         │
                          │  PromptOpinion workspace     │
                          └──────────────────────────────┘
```

## Models

| Step | Model | Why |
|---|---|---|
| Text → FHIR | OpenAI GPT-4o | Strong native structured-output mode |
| Diagnosis | Anthropic Claude Opus 4.7 | Strongest medical reasoning |
| A2A agent runtime | LiteLLM-prefixed (default Gemini 2.5 Flash; OpenAI/Anthropic also supported) | ADK convention |

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# fill in OPENAI_API_KEY, ANTHROPIC_API_KEY, GOOGLE_API_KEY (or your chosen LLM key),
# API_KEY_PRIMARY (any string, used to authenticate calls to the A2A agent),
# PO_PLATFORM_BASE_URL (your Prompt Opinion workspace URL)
```

## Run locally

```bash
# Terminal 1 — MCP server
uvicorn mcp_app.main:app --host 0.0.0.0 --port 8010

# Terminal 2 — A2A agent
uvicorn a2a_app.clinical_scribe_agent.app:a2a_app --host 0.0.0.0 --port 8020
```

Verify each:

```bash
curl http://localhost:8020/.well-known/agent-card.json        # A2A card
```

Test the MCP server end-to-end against any FHIR R4 server:

```bash
python <<'PY'
import asyncio, os
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

async def main():
    headers = {
        "x-fhir-server-url": os.environ["FHIR_BASE_URL"],
        "x-fhir-access-token": os.environ["FHIR_ACCESS_TOKEN"],
    }
    async with streamablehttp_client("http://127.0.0.1:8010/mcp", headers=headers) as (r, w, _):
        async with ClientSession(r, w) as s:
            await s.initialize()
            tools = await s.list_tools()
            print([t.name for t in tools.tools])
            res = await s.call_tool(
                "FindPatient",
                {"firstName": "Edward", "lastName": "Balistreri"},
            )
            print(res.content[0].text)

asyncio.run(main())
PY
```

## Publishing to Prompt Opinion

### MCP server (mcp_app/)

1. **Deploy** with a public URL (Cloud Run, Fly, Render, Railway):
   ```bash
   uvicorn mcp_app.main:app --host 0.0.0.0 --port 8010
   ```
2. **Register** on the Prompt Opinion Marketplace by giving it the URL of
   your deployed `/mcp` endpoint, e.g. `https://your-host.example.com/mcp`.
3. The platform reads the server's capabilities on first connect and sees the
   `ai.promptopinion/fhir-context` extension declaring the SMART scopes the
   server needs. The workspace admin grants those scopes; from then on the
   platform injects `x-fhir-server-url` / `x-fhir-access-token` / `x-patient-id`
   on every tool call.

### A2A agent (a2a_app/)

1. **Deploy** with a public URL:
   ```bash
   uvicorn a2a_app.clinical_scribe_agent.app:a2a_app --host 0.0.0.0 --port 8020
   ```
   Set `CLINICAL_SCRIBE_AGENT_URL` to the public URL so it lands in the
   agent card's `supportedInterfaces`.
2. **Register** the agent card URL on Prompt Opinion:
   `https://your-host.example.com/.well-known/agent-card.json`. Provide the
   `X-API-Key` value you set in `API_KEY_PRIMARY` so the platform can call you.
3. The platform reads the card, sees the `fhir-context` extension URI, and
   starts injecting FHIR context into `params.message.metadata` on every
   `message/send`. Our `extract_fhir_context` hook lifts those into ADK
   session state where the tools read them.

For full Cloud Run / Docker deployment recipes, see the upstream
[po-adk-python](https://github.com/prompt-opinion/po-adk-python) reference —
the `a2a_app/shared/` files are forked from there and behave identically.

## SHARP / FHIR-context contract (cheat sheet)

### MCP server (HTTP headers — per request)

| Header | Required | Purpose |
|---|---|---|
| `x-fhir-server-url` | yes | FHIR R4 base URL |
| `x-fhir-access-token` | yes | Bearer token (also parsed for `patient` JWT claim) |
| `x-patient-id` | optional | Active patient id (fallback if not in JWT) |

Capability advertisement on `initialize`:

```json
{
  "extensions": {
    "ai.promptopinion/fhir-context": {
      "scopes": [{"name": "patient/Patient.rs", "required": true}, ...]
    }
  }
}
```

### A2A agent (A2A v1 JSON-RPC — per request)

```jsonc
{
  "jsonrpc": "2.0",
  "method": "message/send",
  "params": {
    "message": {
      "role": "user",
      "messageId": "...",
      "metadata": {
        "https://your-workspace.promptopinion.ai/schemas/a2a/v1/fhir-context": {
          "fhirUrl":   "https://workspace.fhir.example/r4",
          "fhirToken": "<bearer>",
          "patientId": "patient-uuid"
        }
      },
      "parts": [{"kind": "text", "text": "..."}]
    }
  }
}
```

Headers:
- `X-API-Key: <one of API_KEYS or API_KEY_*>`

The agent card declares the FHIR-context extension URI and the SMART scopes
it requires. The platform handles credential plumbing.

## Project layout

```
.
├── mcp_app/                ★ publishable: MCP server (SHARP-on-MCP)
│   ├── main.py             streamable-http entry point
│   ├── mcp_instance.py     FastMCP + capability advertisement
│   ├── fhir_client.py      bearer-token httpx client
│   ├── fhir_context.py     resolves x-fhir-* headers
│   └── tools/
│       ├── find_patient_tool.py
│       ├── patient_history_tool.py
│       ├── structure_conversation_tool.py
│       ├── suggest_diagnosis_tool.py
│       └── commit_encounter_tool.py
│
├── a2a_app/                ★ publishable: A2A agent (Google ADK + a2a-sdk v1)
│   ├── shared/             app_factory, fhir_hook, middleware (forked from po-adk-python)
│   │   └── tools/          FHIR query + clinical scribe tools
│   └── clinical_scribe_agent/
│       ├── agent.py        ADK Agent w/ before_model_callback = extract_fhir_context
│       └── app.py          create_a2a_app(...) — agent card, scopes, skills
│
└── shared/                 cross-app helpers imported by both publishable apps
    ├── fhir/
    │   ├── schemas.py      Pydantic StructuredEncounterPayload, DiagnosisSuggestion
    │   └── bundle.py       build_resources_from_payload (payload → FHIR R4 resources)
    └── agents/
        └── structurer.py   structure_transcript (GPT-4o structured output)
```

> Note: `shared/` (top-level) and `a2a_app/shared/` are unrelated. The former
> holds cross-app clinical helpers we own; the latter is the per-agent ADK
> scaffolding forked from po-adk-python.

## Reference implementations

The two publishable artifacts follow the official Prompt Opinion patterns:

- MCP — [prompt-opinion/po-community-mcp](https://github.com/prompt-opinion/po-community-mcp)
- A2A — [prompt-opinion/po-adk-python](https://github.com/prompt-opinion/po-adk-python)
- SHARP-on-MCP — [sharponmcp.com](https://www.sharponmcp.com/)
