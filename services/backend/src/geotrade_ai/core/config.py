from functools import lru_cache
from pathlib import Path

from pydantic import ValidationInfo, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# services/backend/src/geotrade_ai/core/config.py -> repo root
REPO_ROOT = Path(__file__).resolve().parents[5]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(REPO_ROOT / ".env", ".env"), extra="ignore")

    app_version: str = "0.1.0"
    log_level: str = "INFO"
    database_url: str = "postgresql+psycopg://geotrade:geotrade-dev@localhost:5432/geotrade"
    db_pool_size: int = 5
    cors_origins: str = "http://localhost:3000"
    operator_token: str = ""
    data_dir: Path = REPO_ROOT / "data"

    # LLM (Qwen 3.8 27B on Groq); keyword scorer is the fallback
    enable_llm: bool = False
    llm_provider: str = "groq"
    llm_model: str = "qwen/qwen3.8-27b"
    llm_base_url: str = "https://api.groq.com/openai/v1"
    groq_api_key: str = ""
    llm_daily_budget: int = 150
    llm_per_minute: int = 5  # Groq free tier: 8K tokens/min is about 5 batches of 10 headlines
    llm_batch_size: int = 10
    llm_timeout_s: float = 20.0

    # worker
    enable_prices: bool = True
    feed_poll_seconds: int = 60
    pipeline_tick_seconds: float = 3.0
    pipeline_batch_size: int = 50
    article_max_age_hours: int = 72
    worker_metrics_port: int = 9101

    # auth (Phase 2)
    jwt_secret: str = "dev-only-change-me-jwt-secret-32-bytes!!"
    refresh_token_pepper: str = "dev-only-change-me-pepper"
    access_ttl_minutes: int = 15
    refresh_ttl_days: int = 30
    cookie_secure: bool = False  # true behind HTTPS (Render / Railway)
    # Next.js rewrites forward the browser IP in X-Forwarded-For.
    # shortcut: trusted unconditionally; restrict to the proxy's address if the API is exposed directly.
    trust_forwarded_for: bool = True
    rate_limit_auth_per_min: int = 10
    rate_limit_upload_per_min: int = 10
    rate_limit_default_per_min: int = 300
    operator_email: str = ""
    operator_password: str = ""

    # api
    cache_ttl_seconds: float = 20.0
    sse_heartbeat_seconds: float = 15.0

    @field_validator("jwt_secret", "refresh_token_pepper", mode="before")
    @classmethod
    def _strong_secret(cls, v: str, info: ValidationInfo) -> str:
        if not v:  # unset: keep the development default (never deploy without setting it)
            return str(cls.model_fields[info.field_name or ""].default)
        if len(v) < 32:
            raise ValueError(f"{(info.field_name or '').upper()} must be at least 32 characters")
        return v

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
