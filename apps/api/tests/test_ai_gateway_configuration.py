from __future__ import annotations

import pytest
from fixtures.ai_gateway import NOOP_AI_PROVENANCE, trusted_ai_context
from pydantic import SecretStr, ValidationError

from privexa_api.access_control.permissions import Permission
from privexa_api.ai_gateway import (
    AIExecutionRequest,
    AIExecutionStatus,
    AITaskType,
    PrepareWorkNoteInput,
    SyntheticTextSummaryInput,
)
from privexa_api.ai_gateway.errors import AIErrorCategory
from privexa_api.ai_gateway.factory import build_ai_gateway
from privexa_api.ai_policy.repository import StaticAIPolicyRepository
from privexa_api.ai_protection.contracts import DetectedEntity
from privexa_api.config import Settings
from privexa_api.security.enums import SensitivityLevel


class EmptyDetector:
    def detect(self, *args: object, **kwargs: object) -> tuple[DetectedEntity, ...]:
        return ()


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "APP_DATABASE_URL": "postgresql+psycopg://unused",
        "STYTCH_PROJECT_ID": "project-test",
        "STYTCH_SECRET": SecretStr("secret-test"),
        "PRIVEXA_ENVIRONMENT": "test",
        "OBJECT_STORAGE_ENDPOINT_URL": None,
        "OBJECT_STORAGE_ACCESS_KEY": None,
        "OBJECT_STORAGE_SECRET_KEY": None,
        "AI_GATEWAY_ENABLED": False,
        "AI_PROVIDER_MODE": "disabled",
        "OPENROUTER_API_KEY": None,
        "AI_SYNTHETIC_TEXT_SUMMARY_MODEL": None,
        "AI_PREPARE_WORK_NOTE_MODEL": None,
        "AI_APPROVED_OPENROUTER_MODELS": [],
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


def test_ai_configuration_defaults_to_disabled_without_provider_secret() -> None:
    settings = _settings()
    assert settings.ai_gateway_enabled is False
    assert settings.ai_provider_mode == "disabled"
    assert settings.openrouter_api_key is None


def test_openrouter_mode_accepts_missing_secret_so_startup_remains_available() -> None:
    settings = _settings(
        PRIVEXA_ENVIRONMENT="development",
        AI_GATEWAY_ENABLED=True,
        AI_PROVIDER_MODE="openrouter",
        AI_PREPARE_WORK_NOTE_MODEL="test/work-note-model",
        AI_APPROVED_OPENROUTER_MODELS=["test/work-note-model"],
    )
    assert settings.openrouter_api_key is None


def test_test_environment_prohibits_external_paid_provider_even_with_a_secret() -> None:
    with pytest.raises(ValidationError, match="prohibits external AI providers"):
        _settings(
            AI_GATEWAY_ENABLED=True,
            AI_PROVIDER_MODE="openrouter",
            OPENROUTER_API_KEY=SecretStr("must-never-be-used"),
            AI_PREPARE_WORK_NOTE_MODEL="test/work-note-model",
            AI_APPROVED_OPENROUTER_MODELS=["test/work-note-model"],
        )


def test_production_prohibits_the_deterministic_provider() -> None:
    with pytest.raises(ValidationError, match="limited to development and test"):
        _settings(
            PRIVEXA_ENVIRONMENT="production",
            OBJECT_STORAGE_BUCKET="privexa-production",
            AI_GATEWAY_ENABLED=True,
            AI_PROVIDER_MODE="deterministic",
        )


@pytest.mark.parametrize(
    "overrides",
    [
        {"OPENROUTER_API_KEY": SecretStr("   ")},
        {"AI_PREPARE_WORK_NOTE_MODEL": "model-without-provider"},
        {"AI_APPROVED_OPENROUTER_MODELS": ["other/provider-model"]},
        {
            "AI_APPROVED_OPENROUTER_MODELS": [
                "test/work-note-model",
                "test/work-note-model",
            ]
        },
    ],
)
def test_openrouter_configuration_rejects_invalid_values(
    overrides: dict[str, object],
) -> None:
    values: dict[str, object] = {
        "PRIVEXA_ENVIRONMENT": "development",
        "AI_GATEWAY_ENABLED": True,
        "AI_PROVIDER_MODE": "openrouter",
        "OPENROUTER_API_KEY": SecretStr("test-openrouter-key"),
        "AI_PREPARE_WORK_NOTE_MODEL": "test/work-note-model",
        "AI_APPROVED_OPENROUTER_MODELS": ["test/work-note-model"],
    }
    values.update(overrides)
    with pytest.raises(ValidationError):
        _settings(**values)


@pytest.mark.parametrize("timeout", [0, -1, 60.1, 1_000])
def test_ai_timeout_configuration_rejects_values_outside_platform_bounds(
    timeout: float,
) -> None:
    with pytest.raises(ValidationError):
        _settings(AI_REQUEST_TIMEOUT_SECONDS=timeout)


@pytest.mark.asyncio
async def test_factory_built_disabled_gateway_starts_without_secret_and_rejects_execution() -> None:
    gateway = build_ai_gateway(_settings(), provenance=NOOP_AI_PROVENANCE)
    try:
        result = await gateway.execute(
            context=trusted_ai_context(),
            request=AIExecutionRequest(
                task=AITaskType.SYNTHETIC_TEXT_SUMMARY,
                input_data=SyntheticTextSummaryInput(text="synthetic"),
            ),
        )
    finally:
        await gateway.aclose()
    assert result.status is AIExecutionStatus.REJECTED
    assert result.error is not None
    assert result.error.category is AIErrorCategory.GATEWAY_DISABLED


@pytest.mark.asyncio
async def test_deterministic_mode_runs_real_gateway_without_external_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "privexa_api.ai_gateway.factory.build_presidio_detector",
        lambda **_: EmptyDetector(),
    )
    gateway = build_ai_gateway(
        _settings(AI_GATEWAY_ENABLED=True, AI_PROVIDER_MODE="deterministic"),
        provenance=NOOP_AI_PROVENANCE,
        policy_repository=StaticAIPolicyRepository(),
    )
    try:
        result = await gateway.execute(
            context=trusted_ai_context(
                sensitivity=SensitivityLevel.SENSITIVE,
                permission=Permission.FILE_READ,
            ),
            request=AIExecutionRequest(
                task=AITaskType.PREPARE_WORK_NOTE,
                input_data=PrepareWorkNoteInput(note="Synthetic client work note."),
            ),
        )
    finally:
        await gateway.aclose()
    assert result.status is AIExecutionStatus.SUCCEEDED
    assert result.execution.provider == "DETERMINISTIC_LOCAL"
    assert result.usage is not None
    assert result.usage.reported_cost == 0


@pytest.mark.asyncio
async def test_missing_openrouter_secret_returns_safe_configuration_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "privexa_api.ai_gateway.factory.build_presidio_detector",
        lambda **_: EmptyDetector(),
    )
    gateway = build_ai_gateway(
        _settings(
            PRIVEXA_ENVIRONMENT="development",
            AI_GATEWAY_ENABLED=True,
            AI_PROVIDER_MODE="openrouter",
            AI_PREPARE_WORK_NOTE_MODEL="test/work-note-model",
            AI_APPROVED_OPENROUTER_MODELS=["test/work-note-model"],
        ),
        provenance=NOOP_AI_PROVENANCE,
        policy_repository=StaticAIPolicyRepository(),
    )
    try:
        result = await gateway.execute(
            context=trusted_ai_context(
                sensitivity=SensitivityLevel.SENSITIVE,
                permission=Permission.FILE_READ,
            ),
            request=AIExecutionRequest(
                task=AITaskType.PREPARE_WORK_NOTE,
                input_data=PrepareWorkNoteInput(note="Synthetic client work note."),
            ),
        )
    finally:
        await gateway.aclose()
    assert result.status is AIExecutionStatus.REJECTED
    assert result.error is not None
    assert result.error.category is AIErrorCategory.NO_COMPLIANT_ROUTE
