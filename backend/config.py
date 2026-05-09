from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


BACKEND_DIR = Path(__file__).resolve().parent
APP_DIR = BACKEND_DIR.parent
PROJECT_ROOT = APP_DIR.parent
DATA_DIR = BACKEND_DIR / "data"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=APP_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    openai_api_key: str = ""
    anthropic_api_key: str = ""

    whisper_model: str = "whisper-1"
    structuring_model: str = "gpt-4o-2024-11-20"
    diagnosis_model: str = "claude-opus-4-7"

    fhir_mode: str = "local"  # "local" | "remote"
    fhir_base_url: str = "http://localhost:8080/fhir"

    app_host: str = "127.0.0.1"
    app_port: int = 8000

    @property
    def patients_store_path(self) -> Path:
        return DATA_DIR / "patients_store.json"

    @property
    def seed_bundle_path(self) -> Path:
        return PROJECT_ROOT / "sample-patient.json"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
