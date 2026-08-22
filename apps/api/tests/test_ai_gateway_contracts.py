from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from typing import cast
from uuid import uuid4

import pytest
from pydantic import BaseModel, ValidationError

from privexa_api.ai_gateway.contracts import (
    AIConstraintOverrides,
    AIExecutionRequest,
    AIExecutionResult,
    AIExecutionStatus,
    AIModelExecutionMetadata,
    AISourceReference,
    AITaskType,
    AIUsage,
)
from privexa_api.ai_gateway.errors import AIError, AIErrorCategory, AIPolicyViolation
from privexa_api.ai_gateway.tasks import (
    SYNTHETIC_TEXT_SUMMARY_TASK,
    AIExecutionConstraints,
    SyntheticTextSummaryInput,
    SyntheticTextSummaryResult,
    build_task_registry,
)


def _execution_metadata() -> AIModelExecutionMetadata:
    now = datetime.now(UTC)
    return AIModelExecutionMetadata(started_at=now, completed_at=now, latency_ms=0)


@pytest.mark.parametrize("text", ["", "   ", "\n\t"])
def test_synthetic_input_rejects_empty_content(text: str) -> None:
    with pytest.raises(ValidationError) as captured:
        SyntheticTextSummaryInput(text=text)

    assert captured.value.errors()[0]["loc"] == ("text",)
    assert captured.value.errors()[0]["type"] == "string_too_short"


def test_synthetic_input_accepts_exact_limit_and_rejects_above_limit() -> None:
    assert len(SyntheticTextSummaryInput(text="x" * 2_000).text) == 2_000

    with pytest.raises(ValidationError) as captured:
        SyntheticTextSummaryInput(text="x" * 2_001)

    assert captured.value.errors()[0]["type"] == "string_too_long"


@pytest.mark.parametrize(
    "extra_field",
    ["system_prompt", "provider_prompt", "model", "client_id", "firm_id"],
)
def test_synthetic_input_forbids_caller_control_fields(extra_field: str) -> None:
    with pytest.raises(ValidationError) as captured:
        SyntheticTextSummaryInput.model_validate(
            {"text": "synthetic", extra_field: "unapproved control"}
        )

    assert captured.value.errors()[0]["loc"] == (extra_field,)
    assert captured.value.errors()[0]["type"] == "extra_forbidden"


@pytest.mark.parametrize(
    "payload",
    [{}, {"wrong_field": "value"}, {"summary": "valid", "model": "unapproved"}],
)
def test_synthetic_output_rejects_incomplete_or_extra_fields(payload: dict[str, str]) -> None:
    with pytest.raises(ValidationError):
        SyntheticTextSummaryResult.model_validate(payload)


def test_task_result_schema_does_not_contain_provider_usage_fields() -> None:
    assert set(SyntheticTextSummaryResult.model_fields) == {"summary"}


def test_request_rejects_unknown_task_identifier_and_extra_model_control() -> None:
    with pytest.raises(ValidationError) as unknown_task:
        AIExecutionRequest.model_validate(
            {
                "task": "unknown_privexa_task",
                "input_data": SyntheticTextSummaryInput(text="synthetic"),
            }
        )
    assert unknown_task.value.errors()[0]["loc"] == ("task",)
    assert unknown_task.value.errors()[0]["type"] == "is_instance_of"

    with pytest.raises(ValidationError) as extra_model:
        AIExecutionRequest.model_validate(
            {
                "task": AITaskType.SYNTHETIC_TEXT_SUMMARY,
                "input_data": SyntheticTextSummaryInput(text="synthetic"),
                "model": "provider/arbitrary-model",
            }
        )
    assert extra_model.value.errors()[0]["loc"] == ("model",)
    assert extra_model.value.errors()[0]["type"] == "extra_forbidden"


def test_request_bounds_source_reference_batch_before_authorization() -> None:
    references = tuple(
        AISourceReference(source_type="stored_file", source_id=uuid4()) for _ in range(101)
    )

    with pytest.raises(ValidationError) as captured:
        AIExecutionRequest(
            task=AITaskType.SYNTHETIC_TEXT_SUMMARY,
            input_data=SyntheticTextSummaryInput(text="synthetic"),
            source_references=references,
        )

    assert captured.value.errors()[0]["loc"] == ("source_references",)
    assert captured.value.errors()[0]["type"] == "too_long"

    accepted = AIExecutionRequest(
        task=AITaskType.SYNTHETIC_TEXT_SUMMARY,
        input_data=SyntheticTextSummaryInput(text="synthetic"),
        source_references=references[:100],
    )
    assert len(accepted.source_references) == 100


def test_source_reference_rejects_caller_supplied_ownership_metadata() -> None:
    with pytest.raises(ValidationError) as captured:
        AISourceReference.model_validate(
            {
                "source_type": "stored_file",
                "source_id": uuid4(),
                "client_id": uuid4(),
            }
        )

    assert captured.value.errors()[0]["loc"] == ("client_id",)
    assert captured.value.errors()[0]["type"] == "extra_forbidden"


@pytest.mark.parametrize(
    ("factory", "field"),
    [
        (lambda: AIConstraintOverrides(max_output_tokens=0), "max_output_tokens"),
        (lambda: AIConstraintOverrides(timeout_seconds=0), "timeout_seconds"),
        (
            lambda: AIExecutionConstraints(
                max_input_characters=0,
                max_input_tokens=1,
                max_output_tokens=1,
                timeout_seconds=1,
            ),
            "max_input_characters",
        ),
        (lambda: AIUsage(prompt_tokens=-1), "prompt_tokens"),
        (lambda: AIUsage(reported_cost=-1), "reported_cost"),
    ],
)
def test_constraint_and_usage_contracts_reject_invalid_values(factory, field: str) -> None:
    with pytest.raises(ValidationError) as captured:
        factory()

    assert captured.value.errors()[0]["loc"] == (field,)


def test_execution_result_enforces_success_and_failure_invariants() -> None:
    with pytest.raises(ValidationError, match="successful AI execution requires a task, result"):
        AIExecutionResult[BaseModel](
            execution_id=uuid4(),
            task=AITaskType.SYNTHETIC_TEXT_SUMMARY,
            status=AIExecutionStatus.SUCCEEDED,
            execution=_execution_metadata(),
        )

    with pytest.raises(ValidationError, match="successful AI execution requires a task, result"):
        AIExecutionResult[BaseModel](
            execution_id=uuid4(),
            task=None,
            status=AIExecutionStatus.SUCCEEDED,
            result=SyntheticTextSummaryResult(summary="valid but unattributed"),
            execution=_execution_metadata(),
        )

    with pytest.raises(ValidationError, match="unsuccessful AI execution requires an error"):
        AIExecutionResult[BaseModel](
            execution_id=uuid4(),
            task=AITaskType.SYNTHETIC_TEXT_SUMMARY,
            status=AIExecutionStatus.FAILED,
            result=SyntheticTextSummaryResult(summary="not allowed"),
            execution=_execution_metadata(),
        )


def test_normalized_error_uses_safe_stable_message() -> None:
    error = AIError.safe(AIErrorCategory.PROVIDER_AUTHENTICATION_ERROR)

    assert error.category is AIErrorCategory.PROVIDER_AUTHENTICATION_ERROR
    assert error.retryable is False
    assert "provider" in error.message.lower()
    assert "key" not in error.message.lower()


def test_task_registry_resolves_versioned_immutable_definition() -> None:
    definition = build_task_registry().resolve(AITaskType.SYNTHETIC_TEXT_SUMMARY)

    assert definition is SYNTHETIC_TEXT_SUMMARY_TASK
    assert definition.version == "1"
    with pytest.raises(FrozenInstanceError):
        definition.version = "caller-controlled"  # type: ignore[misc]


def test_task_registry_rejects_unknown_task() -> None:
    unknown = cast(AITaskType, "unknown_privexa_task")

    with pytest.raises(AIPolicyViolation) as captured:
        build_task_registry().resolve(unknown)

    assert captured.value.category is AIErrorCategory.UNSUPPORTED_TASK
