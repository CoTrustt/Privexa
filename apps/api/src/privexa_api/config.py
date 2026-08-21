from __future__ import annotations

import os
from functools import lru_cache
from typing import Literal

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
