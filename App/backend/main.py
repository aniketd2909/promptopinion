from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.config import APP_DIR, get_settings
from backend.routes import dev_fhir, encounters, patients


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="PromptOpinion — Clinical Scribe",
        description=(
            "AI-powered clinical scribe. Records doctor-patient conversation, "
            "produces FHIR-shaped data, fetches patient history via MCP, and "
            "suggests diagnostic next steps for the doctor to approve."
        ),
        version="0.1.0",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(patients.router)
    app.include_router(encounters.router)
    app.include_router(dev_fhir.router)

    @app.get("/api/health")
    def health() -> dict:
        return {
            "status": "ok",
            "fhir_mode": settings.fhir_mode,
            "models": {
                "transcription": settings.whisper_model,
                "structuring": settings.structuring_model,
                "diagnosis": settings.diagnosis_model,
            },
        }

    # Serve the bundled HTML/JS frontend at the root.
    frontend_dir: Path = APP_DIR / "frontend"
    if frontend_dir.exists():
        app.mount(
            "/static",
            StaticFiles(directory=frontend_dir),
            name="static",
        )

        @app.get("/")
        def index() -> FileResponse:
            return FileResponse(frontend_dir / "index.html")

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "backend.main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=False,
    )
