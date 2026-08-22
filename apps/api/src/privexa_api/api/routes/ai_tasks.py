from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from privexa_api.access_control.permissions import Permission
from privexa_api.ai_gateway.availability import AICapability, AICapabilityState
from privexa_api.ai_gateway.contracts import (
    MAX_AI_SOURCE_REFERENCES,
    AIExecutionRequest,
    AIExecutionStatus,
    AISourceReference,
)
from privexa_api.ai_gateway.errors import AIErrorCategory
from privexa_api.ai_gateway.gateway import AIGateway
from privexa_api.ai_gateway.tasks import PrepareWorkNoteInput, PrepareWorkNoteResult
from privexa_api.ai_provenance.hashing import hash_output
from privexa_api.ai_types import AITaskType
from privexa_api.api.authorization_dependencies import require_active_client_permission
from privexa_api.api.dependencies import get_ai_gateway, get_database_session
from privexa_api.security.enums import SensitivityLevel
from privexa_api.security.execution_context import ExecutionContext

router = APIRouter(prefix="/ai/tasks", tags=["ai-tasks"])

DatabaseSession = Annotated[Session, Depends(get_database_session)]
Gateway = Annotated[AIGateway, Depends(get_ai_gateway)]
PrepareContext = Annotated[
    ExecutionContext,
    Depends(require_active_client_permission(Permission.FILE_READ)),
]


class PrepareWorkNoteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    note: str = Field(min_length=1, max_length=5_000)
    source_file_ids: tuple[UUID, ...] = Field(
        default=(),
        max_length=MAX_AI_SOURCE_REFERENCES,
    )


class PreparedWorkNoteCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    client_id: UUID
    execution_id: UUID
    task_id: Literal["ai.prepare_work_note"] = "ai.prepare_work_note"
    task_version: Literal["1"] = "1"
    output_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    draft: str
    suggested_follow_up: str
    caveat: str | None
    review_required: Literal[True] = True
    authoritative: Literal[False] = False


class AIWorkNoteProblem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str
    detail: str
    retryable: bool = False
    retry_after_seconds: int | None = None


class PrepareWorkNoteResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["PREPARED", "RESTRICTED", "FAILED"]
    execution_id: UUID
    candidate: PreparedWorkNoteCandidate | None = None
    problem: AIWorkNoteProblem | None = None


class AITaskCapabilityResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    task_id: Literal["ai.prepare_work_note"] = "ai.prepare_work_note"
    state: AICapabilityState
    available: bool
    retryable: bool
    retry_after_seconds: int | None = None


@router.get(
    "/ai.prepare_work_note/capability",
    response_model=AITaskCapabilityResponse,
)
def prepare_work_note_capability(
    response: Response,
    context: PrepareContext,
    session: DatabaseSession,
    gateway: Gateway,
) -> AITaskCapabilityResponse:
    response.headers["Cache-Control"] = "no-store"
    capability: AICapability = gateway.capability(
        context=context.with_minimum_sensitivity(SensitivityLevel.SENSITIVE),
        task_type=AITaskType.PREPARE_WORK_NOTE,
        session=session,
    )
    return AITaskCapabilityResponse(
        state=capability.state,
        available=capability.available,
        retryable=capability.retryable,
        retry_after_seconds=capability.retry_after_seconds,
    )


@router.post(
    "/ai.prepare_work_note/prepare",
    response_model=PrepareWorkNoteResponse,
)
async def prepare_work_note(
    payload: PrepareWorkNoteRequest,
    response: Response,
    context: PrepareContext,
    session: DatabaseSession,
    gateway: Gateway,
) -> PrepareWorkNoteResponse:
    response.headers["Cache-Control"] = "no-store"
    protected_context = context.with_minimum_sensitivity(SensitivityLevel.SENSITIVE)
    result = await gateway.execute(
        context=protected_context,
        request=AIExecutionRequest(
            task=AITaskType.PREPARE_WORK_NOTE,
            input_data=PrepareWorkNoteInput(note=payload.note),
            source_references=tuple(
                AISourceReference(source_type="stored_file", source_id=source_id)
                for source_id in payload.source_file_ids
            ),
        ),
        session=session,
    )
    if result.status is AIExecutionStatus.SUCCEEDED and isinstance(
        result.result, PrepareWorkNoteResult
    ):
        candidate_output = result.result
        return PrepareWorkNoteResponse(
            status="PREPARED",
            execution_id=result.execution_id,
            candidate=PreparedWorkNoteCandidate(
                client_id=protected_context.client_id,  # type: ignore[arg-type]
                execution_id=result.execution_id,
                output_hash=hash_output(candidate_output),
                **candidate_output.model_dump(),
            ),
        )

    error = result.error
    category = error.category if error is not None else AIErrorCategory.INTERNAL_ERROR
    code, detail, restricted = _public_problem(category)
    return PrepareWorkNoteResponse(
        status="RESTRICTED" if restricted else "FAILED",
        execution_id=result.execution_id,
        problem=AIWorkNoteProblem(
            code=code,
            detail=detail,
            retryable=error.retryable if error is not None else False,
            retry_after_seconds=error.retry_after_seconds if error is not None else None,
        ),
    )


def _public_problem(category: AIErrorCategory) -> tuple[str, str, bool]:
    if category in {
        AIErrorCategory.CLIENT_BOUNDARY_VIOLATION,
        AIErrorCategory.POLICY_DENIED,
    }:
        return (
            "AI_CONTEXT_RESTRICTED",
            "Preparation with Privexa is not available for this client context. "
            "You can continue manually.",
            True,
        )
    mapping = {
        AIErrorCategory.GATEWAY_DISABLED: (
            "AI_DISABLED",
            "Privexa assistance is temporarily unavailable. You can continue working normally.",
        ),
        AIErrorCategory.TASK_DISABLED: (
            "AI_TASK_UNAVAILABLE",
            "Preparation with Privexa is currently unavailable. You can continue manually.",
        ),
        AIErrorCategory.PROVIDER_DISABLED: (
            "AI_UNAVAILABLE",
            "Privexa assistance is temporarily unavailable. You can continue working normally.",
        ),
        AIErrorCategory.CIRCUIT_OPEN: (
            "AI_TEMPORARILY_UNAVAILABLE",
            "Privexa couldn't prepare this right now. Your work has been preserved.",
        ),
        AIErrorCategory.RESULT_AUTHORITY_REVOKED: (
            "AI_RESULT_DISCARDED",
            "Privexa assistance became unavailable before the draft was ready. "
            "Your manual note is unchanged.",
        ),
        AIErrorCategory.CONFIGURATION_ERROR: (
            "AI_PROVIDER_NOT_CONFIGURED",
            "Preparation with Privexa is not configured. Your manual note is unchanged.",
        ),
        AIErrorCategory.NO_COMPLIANT_ROUTE: (
            "AI_PROVIDER_NOT_CONFIGURED",
            "Preparation with Privexa is not configured. Your manual note is unchanged.",
        ),
        AIErrorCategory.TIMEOUT: (
            "AI_TIMEOUT",
            "Preparation took too long. Your manual note is unchanged.",
        ),
        AIErrorCategory.RATE_LIMITED: (
            "AI_RATE_LIMITED",
            "Preparation is temporarily busy. Try again shortly.",
        ),
        AIErrorCategory.PROVIDER_UNAVAILABLE: (
            "AI_PROVIDER_UNAVAILABLE",
            "Preparation is temporarily unavailable. Your manual note is unchanged.",
        ),
        AIErrorCategory.PII_PROTECTION_FAILED: (
            "AI_PROTECTION_FAILED",
            "Privexa could not safely prepare this note. Continue manually.",
        ),
        AIErrorCategory.INVALID_INPUT: (
            "AI_INPUT_LIMIT_EXCEEDED",
            "Shorten the work note before preparing a draft.",
        ),
        AIErrorCategory.STRUCTURED_OUTPUT_INVALID: (
            "AI_INVALID_RESPONSE",
            "Privexa could not prepare a valid draft. Your manual note is unchanged.",
        ),
    }
    code, detail = mapping.get(
        category,
        (
            "AI_PREPARATION_FAILED",
            "Privexa could not prepare this draft. Your manual note is unchanged.",
        ),
    )
    return code, detail, False
