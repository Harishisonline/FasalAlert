"""Application settings from environment variables (see the repo root .env.example)."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

API_ROOT = Path(__file__).resolve().parents[2]  # apps/api
REPO_ROOT = API_ROOT.parents[1]
DATA_DIR = API_ROOT / "data"
SHARED_DIR = REPO_ROOT / "packages" / "shared"

_DEV_SECRET = "change-me-dev-only"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(str(REPO_ROOT / ".env"), str(API_ROOT / ".env")), extra="ignore"
    )

    app_env: str = "development"
    database_url: str = "postgresql+psycopg://fasalalert:fasalalert_dev@localhost:5433/fasalalert"
    test_database_url: str = "postgresql+psycopg://fasalalert:fasalalert_dev@localhost:5433/fasalalert_test"

    jwt_secret: str = _DEV_SECRET
    otp_pepper: str = _DEV_SECRET
    access_token_ttl_seconds: int = 900
    refresh_token_ttl_days: int = 30
    cors_origins: str = "http://localhost:3000"

    open_meteo_forecast_url: str = "https://api.open-meteo.com/v1/forecast"
    open_meteo_ensemble_url: str = "https://ensemble-api.open-meteo.com/v1/ensemble"
    open_meteo_archive_url: str = "https://archive-api.open-meteo.com/v1/archive"
    open_meteo_previous_runs_url: str = "https://previous-runs-api.open-meteo.com/v1/forecast"
    imd_api_key: str = ""

    data_gov_in_api_key: str = ""
    agmarknet_resource_id: str = "9ef84268-d588-465a-a308-a864a43d0070"

    opentopodata_url: str = "https://api.opentopodata.org/v1/srtm30m"
    osrm_url: str = "https://router.project-osrm.org"
    overpass_url: str = "https://overpass-api.de/api/interpreter"

    bhashini_user_id: str = ""
    bhashini_ulca_api_key: str = ""
    bhashini_pipeline_id: str = "64392f96daac500b55c543cd"
    whisper_model: str = ""

    embedding_model: str = "sentence-transformers/paraphrase-multilingual-mpnet-base-v2"
    embedding_dim: int = 768
    rag_min_similarity: float = 0.45

    # Ask assistant LLM (optional). When GROQ_API_KEY is set, answers are drafted with Qwen on Groq
    # from grounded field + RAG context; otherwise the deterministic composer is used.
    groq_api_key: str = ""
    groq_model: str = "qwen/qwen3.8-27b"

    sms_provider: str = "dev_outbox"
    dev_outbox_dir: str = ""   # default data/dev_outbox; tests point it elsewhere so they never wipe a developer's codes
    # When true AND SMS_PROVIDER=dev_outbox AND not production, OTP request responses include demo_code for the UI.
    demo_otp_visible: bool = True
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_from_number: str = ""
    whatsapp_provider: str = "none"
    whatsapp_token: str = ""
    whatsapp_phone_number_id: str = ""
    vapid_public_key: str = ""
    vapid_private_key: str = ""
    vapid_subject: str = "mailto:admin@example.org"
    web_otp_origin: str = "localhost"
    kisan_call_centre: str = "1800-180-1551"

    scheduler_enabled: bool = True
    http_user_agent: str = Field(default="FasalAlert/0.1 (research; contact via repository)")

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def allow_demo_otp(self) -> bool:
        """Demo OTP in API responses: explicit flag + outbox provider + never in production."""
        return self.demo_otp_visible and self.sms_provider == "dev_outbox" and not self.is_production

    def validate_for_startup(self) -> None:
        """PRD §12: refuse to start a deployed environment with default secrets."""
        if self.is_production:
            for name in ("jwt_secret", "otp_pepper"):
                value = getattr(self, name)
                if not value or value == _DEV_SECRET or len(value) < 32:
                    raise RuntimeError(f"{name.upper()} must be set to a strong value in production")
            if self.sms_provider == "dev_outbox":
                raise RuntimeError("SMS_PROVIDER=dev_outbox is development-only")
            if self.demo_otp_visible:
                raise RuntimeError("DEMO_OTP_VISIBLE must be false in production")


@lru_cache
def get_settings() -> Settings:
    return Settings()
