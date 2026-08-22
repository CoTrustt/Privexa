from __future__ import annotations

import os
from decimal import Decimal
from functools import lru_cache
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore", case_sensitive=False)

    environment: Literal["development", "test", "staging", "production"] = Field(
        default="development",
        validation_alias="PRIVEXA_ENVIRONMENT",
    )
    app_database_url: str = Field(validation_alias="APP_DATABASE_URL")
    stytch_project_id: str = Field(validation_alias="STYTCH_PROJECT_ID")
    stytch_secret: SecretStr = Field(validation_alias="STYTCH_SECRET")
    privexa_web_origin: str = Field(
        default="http://localhost:3000",
        validation_alias="PRIVEXA_WEB_ORIGIN",
    )
    auth_cookie_domain: str | None = Field(
        default=None,
        validation_alias="PRIVEXA_AUTH_COOKIE_DOMAIN",
    )
    ai_gateway_enabled: bool = Field(
        default=False,
        validation_alias="AI_GATEWAY_ENABLED",
    )
    ai_provider_mode: Literal["disabled", "deterministic", "openrouter"] = Field(
        default="disabled",
        validation_alias="AI_PROVIDER_MODE",
    )
    openrouter_api_key: SecretStr | None = Field(
        default=None,
        validation_alias="OPENROUTER_API_KEY",
    )
    ai_synthetic_text_summary_model: str | None = Field(
        default=None,
        min_length=3,
        max_length=255,
        validation_alias="AI_SYNTHETIC_TEXT_SUMMARY_MODEL",
    )
    ai_prepare_work_note_model: str | None = Field(
        default=None,
        min_length=3,
        max_length=255,
        validation_alias="AI_PREPARE_WORK_NOTE_MODEL",
    )
    ai_approved_openrouter_models: tuple[str, ...] = Field(
        default=(),
        validation_alias="AI_APPROVED_OPENROUTER_MODELS",
    )
    ai_request_timeout_seconds: float = Field(
        default=20.0,
        ge=1.0,
        le=60.0,
        validation_alias="AI_REQUEST_TIMEOUT_SECONDS",
    )
    ai_max_prompt_price_usd_per_million_tokens: Decimal = Field(
        default=Decimal("1.00"),
        gt=0,
        validation_alias="AI_MAX_PROMPT_PRICE_USD_PER_MILLION_TOKENS",
    )
    ai_max_completion_price_usd_per_million_tokens: Decimal = Field(
        default=Decimal("5.00"),
        gt=0,
        validation_alias="AI_MAX_COMPLETION_PRICE_USD_PER_MILLION_TOKENS",
    )
    ai_max_cost_usd_per_request: Decimal = Field(
        default=Decimal("0.50"),
        gt=0,
        le=Decimal("100.00"),
        validation_alias="AI_MAX_COST_USD_PER_REQUEST",
    )
    ai_circuit_failure_threshold: int = Field(
        default=5,
        ge=1,
        le=100,
        validation_alias="AI_CIRCUIT_FAILURE_THRESHOLD",
    )
    ai_circuit_failure_window_seconds: int = Field(
        default=60,
        ge=1,
        le=3600,
        validation_alias="AI_CIRCUIT_FAILURE_WINDOW_SECONDS",
    )
    ai_circuit_open_seconds: int = Field(
        default=30,
        ge=1,
        le=3600,
        validation_alias="AI_CIRCUIT_OPEN_SECONDS",
    )
    ai_circuit_half_open_success_threshold: int = Field(
        default=2,
        ge=1,
        le=20,
        validation_alias="AI_CIRCUIT_HALF_OPEN_SUCCESS_THRESHOLD",
    )
    ai_circuit_probe_lease_seconds: int = Field(
        default=10,
        ge=1,
        le=300,
        validation_alias="AI_CIRCUIT_PROBE_LEASE_SECONDS",
    )
    object_storage_endpoint_url: str | None = Field(
        default=None,
        validation_alias="OBJECT_STORAGE_ENDPOINT_URL",
    )
    object_storage_region: str = Field(
        default="us-east-1",
        min_length=1,
        validation_alias="OBJECT_STORAGE_REGION",
    )
    object_storage_bucket: str = Field(
        default="privexa-local",
        min_length=3,
        max_length=63,
        pattern=r"^[a-z0-9][a-z0-9.-]*[a-z0-9]$",
        validation_alias="OBJECT_STORAGE_BUCKET",
    )
    object_storage_access_key: SecretStr | None = Field(
        default=None,
        validation_alias="OBJECT_STORAGE_ACCESS_KEY",
    )
    object_storage_secret_key: SecretStr | None = Field(
        default=None,
        validation_alias="OBJECT_STORAGE_SECRET_KEY",
    )
    object_storage_addressing_style: Literal["auto", "path", "virtual"] = Field(
        default="auto",
        validation_alias="OBJECT_STORAGE_ADDRESSING_STYLE",
    )
    file_upload_url_ttl_seconds: int = Field(
        default=900,
        ge=60,
        le=3600,
        validation_alias="FILE_UPLOAD_URL_TTL_SECONDS",
    )
    file_upload_completion_grace_seconds: int = Field(
        default=300,
        ge=0,
        le=1800,
        validation_alias="FILE_UPLOAD_COMPLETION_GRACE_SECONDS",
    )
    file_download_url_ttl_seconds: int = Field(
        default=120,
        ge=30,
        le=900,
        validation_alias="FILE_DOWNLOAD_URL_TTL_SECONDS",
    )
    max_file_upload_size_bytes: int = Field(
        default=52_428_800,
        ge=1,
        le=5_368_709_120,
        validation_alias="MAX_FILE_UPLOAD_SIZE_BYTES",
    )

    @model_validator(mode="after")
    def prevent_development_from_using_test_database(self) -> Settings:
        database_name = make_url(self.app_database_url).database
        if (
            self.environment == "development"
            and database_name is not None
            and database_name.lower().endswith("_test")
        ):
            raise ValueError(
                "Development APP_DATABASE_URL must not target a database ending in '_test'"
            )
        return self

    @model_validator(mode="after")
    def validate_object_storage_configuration(self) -> Settings:
        has_access_key = self.object_storage_access_key is not None
        has_secret_key = self.object_storage_secret_key is not None
        if has_access_key != has_secret_key:
            raise ValueError("Object-storage access and secret keys must be configured together")
        if self.object_storage_endpoint_url is not None:
            endpoint = urlsplit(self.object_storage_endpoint_url)
            if (
                endpoint.scheme not in {"http", "https"}
                or not endpoint.netloc
                or endpoint.username is not None
                or endpoint.password is not None
                or endpoint.query
                or endpoint.fragment
            ):
                raise ValueError("Object-storage endpoint must be a valid HTTP(S) origin")
        if (
            self.environment in {"staging", "production"}
            and self.object_storage_endpoint_url is not None
            and not self.object_storage_endpoint_url.startswith("https://")
        ):
            raise ValueError("Staging and production object-storage endpoints must use HTTPS")
        if self.environment in {"staging", "production"} and self.object_storage_bucket == (
            "privexa-local"
        ):
            raise ValueError("Staging and production require an explicit object-storage bucket")
        return self

    @model_validator(mode="after")
    def validate_ai_gateway_configuration(self) -> Settings:
        if not self.ai_gateway_enabled:
            return self
        if self.ai_provider_mode == "disabled":
            return self
        if self.environment == "test" and self.ai_provider_mode == "openrouter":
            raise ValueError("Test environment prohibits external AI providers")
        if self.environment in {"staging", "production"} and self.ai_provider_mode == (
            "deterministic"
        ):
            raise ValueError("Deterministic AI provider is limited to development and test")
        models = (
            self.ai_synthetic_text_summary_model,
            self.ai_prepare_work_note_model,
        )
        if self.ai_provider_mode == "deterministic":
            return self
        if any(
            model is not None and not _valid_provider_model_identifier(model) for model in models
        ):
            raise ValueError("AI model identifier is invalid")
        approved = frozenset(self.ai_approved_openrouter_models)
        if any(not _valid_provider_model_identifier(model) for model in approved):
            raise ValueError("Approved AI model identifier is invalid")
        if len(approved) != len(self.ai_approved_openrouter_models):
            raise ValueError("Approved AI models must not contain duplicates")
        if any(model is not None and model not in approved for model in models):
            raise ValueError("Every configured AI model must be explicitly approved")
        if self.openrouter_api_key is not None:
            api_key = self.openrouter_api_key.get_secret_value()
            if not api_key or any(character.isspace() for character in api_key):
                raise ValueError("OpenRouter API key is invalid")
        return self

    @property
    def auth_cookie_secure(self) -> bool:
        return self.environment in {"staging", "production"}


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]


def get_database_url() -> str:
    """Return the schema-owner URL used only by Alembic and owner operations."""
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL must be set")
    return database_url


def get_runtime_database_role() -> str:
    """Return the login role used by the API so migrations can grant bounded function access."""

    app_database_url = os.getenv("APP_DATABASE_URL")
    if not app_database_url:
        raise RuntimeError("APP_DATABASE_URL must be set while running migrations")
    username = make_url(app_database_url).username
    if not username:
        raise RuntimeError("APP_DATABASE_URL must include a database username")
    return username


def _valid_provider_model_identifier(value: str) -> bool:
    provider, separator, model = value.partition("/")
    return bool(
        separator and provider and model and not any(character.isspace() for character in value)
    )
