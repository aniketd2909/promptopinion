"""Streamable-HTTP MCP server entry point.

Run with::

    uvicorn mcp_app.main:app --host 0.0.0.0 --port 8010

The Prompt Opinion platform connects to this URL, sends FHIR context as
HTTP headers on each tool call, and invokes the registered MCP tools.
"""

from dotenv import load_dotenv
load_dotenv()

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from mcp_app.http import close_http_client
from mcp_app.mcp_instance import mcp


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with mcp.session_manager.run():
        try:
            yield
        finally:
            await close_http_client()


app = FastAPI(
    title="PromptOpinion Clinical Scribe — MCP Server",
    description=(
        "SHARP-on-MCP server providing FHIR-aware clinical scribe tools: "
        "patient lookup, history retrieval, transcript structuring, diagnosis "
        "suggestion, and approved-encounter commit."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount the streamable-http MCP app at the root.
app.mount("/", mcp.streamable_http_app())


if __name__ == "__main__":
    import os

    import uvicorn

    uvicorn.run(
        "mcp_app.main:app",
        host=os.getenv("MCP_HOST", "0.0.0.0"),
        port=int(os.getenv("MCP_PORT", "8010")),
        reload=False,
    )
