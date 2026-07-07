"""Environment configuration. Section 86: "Missing variables cause explicit startup
failure, not silent misbehavior." Loaded once at import time — if a required variable
is absent, the process refuses to start rather than run with an undefined default.
"""
from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- Required, no defaults (Section 86 required env vars) ---
    anthropic_api_key: str = Field(alias="ANTHROPIC_API_KEY")
    supabase_url: str = Field(alias="SUPABASE_URL")
    supabase_service_role_key: str = Field(alias="SUPABASE_SERVICE_ROLE_KEY")
    database_url: str = Field(alias="DATABASE_URL")
    secret_key: str = Field(alias="SECRET_KEY")

    # The RLS-bound runtime pool (arx/db/connection.py) must NOT connect as the DB
    # superuser/service role — Postgres superusers (and any role with BYPASSRLS)
    # ignore every RLS policy outright, `FORCE ROW LEVEL SECURITY` notwithstanding
    # (that clause only forces RLS on the table *owner*, never on a bypass-privileged
    # role). DATABASE_URL is reserved for scripts/migrate.py and scripts/seed_org.py,
    # which are platform-bootstrap operations that are supposed to bypass RLS.
    # Defaults to DATABASE_URL for convenience, but production must set this to a
    # distinct, non-bypass-privileged role (Supabase's `authenticated` role, or the
    # NOBYPASSRLS role created by arx/db/local_dev/auth_shim.sql locally).
    app_database_url: str = Field(default="", alias="APP_DATABASE_URL")

    @field_validator("app_database_url")
    @classmethod
    def _default_app_database_url(cls, v: str, info) -> str:
        return v or info.data.get("database_url", "")

    # --- Required, with documented defaults ---
    supabase_anon_key: str = Field(default="", alias="SUPABASE_ANON_KEY")
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")
    environment: str = Field(default="development", alias="ENVIRONMENT")
    default_org_id: str | None = Field(default=None, alias="DEFAULT_ORG_ID")
    model_name: str = Field(default="claude-sonnet-4-20250514", alias="MODEL_NAME")
    max_tokens_default: int = Field(default=4096, alias="MAX_TOKENS_DEFAULT")
    token_budget_monthly_default: int = Field(default=500_000, alias="TOKEN_BUDGET_MONTHLY_DEFAULT")
    supabase_storage_bucket: str = Field(default="arx-documents", alias="SUPABASE_STORAGE_BUCKET")

    @field_validator("environment")
    @classmethod
    def _valid_environment(cls, v: str) -> str:
        if v not in ("development", "staging", "production"):
            raise ValueError(f"ENVIRONMENT must be development|staging|production, got {v!r}")
        return v

    @field_validator("max_tokens_default")
    @classmethod
    def _min_max_tokens(cls, v: int) -> int:
        # Section 86: "Never set below 2048."
        if v < 2048:
            raise ValueError("MAX_TOKENS_DEFAULT must never be set below 2048")
        return v

    @field_validator("default_org_id")
    @classmethod
    def _no_default_org_in_production(cls, v: str | None, info) -> str | None:
        # Section 86: "Used in development only. Never set in production."
        environment = info.data.get("environment")
        if v and environment == "production":
            raise ValueError("DEFAULT_ORG_ID must never be set when ENVIRONMENT=production")
        return v


@lru_cache
def get_settings() -> Settings:
    """Raises pydantic.ValidationError (explicit startup failure) if any required
    variable is missing or invalid — never falls back to a silent default."""
    return Settings()
