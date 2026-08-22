from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from privexa_api.access_control.permissions import Permission
from privexa_api.api.authorization_dependencies import require_active_client_path_permission
from privexa_api.api.dependencies import get_database_session
from privexa_api.questions.enums import QuestionStatus
from privexa_api.questions.schemas import (
    CreateQuestionRequest,
    QuestionLifecycleRequest,
    QuestionListResponse,
    QuestionPageMetadata,
    QuestionResponse,
    UpdateQuestionRequest,
    question_response,
)
from privexa_api.questions.service import QuestionService
from privexa_api.security.execution_context import ExecutionContext

router = APIRouter(prefix="/clients/{client_id}/questions", tags=["questions"])

DatabaseSession = Annotated[Session, Depends(get_database_session)]
QuestionReadContext = Annotated[
    ExecutionContext,
    Depends(require_active_client_path_permission(Permission.QUESTION_READ)),
]
QuestionCreateContext = Annotated[
    ExecutionContext,
    Depends(require_active_client_path_permission(Permission.QUESTION_CREATE)),
]
QuestionUpdateContext = Annotated[
    ExecutionContext,
    Depends(require_active_client_path_permission(Permission.QUESTION_UPDATE)),
]


@router.post(
    "",
    response_model=QuestionResponse,
    status_code=201,
    summary="Create a Question",
)
def create_question(
    client_id: UUID,
    payload: CreateQuestionRequest,
    response: Response,
    context: QuestionCreateContext,
    session: DatabaseSession,
) -> QuestionResponse:
    question = QuestionService.create(session, context=context, request=payload)
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Location"] = f"/v1/clients/{client_id}/questions/{question.id}"
    return question_response(question)


@router.get(
    "",
    response_model=QuestionListResponse,
    summary="List Questions",
)
def list_questions(
    response: Response,
    context: QuestionReadContext,
    session: DatabaseSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    status: QuestionStatus | None = None,
) -> QuestionListResponse:
    page = QuestionService.list(
        session,
        context=context,
        limit=limit,
        offset=offset,
        status=status,
    )
    response.headers["Cache-Control"] = "private, no-store"
    return QuestionListResponse(
        items=tuple(question_response(question) for question in page.items),
        page=QuestionPageMetadata(limit=limit, offset=offset, has_more=page.has_more),
    )


@router.get(
    "/{question_id}",
    response_model=QuestionResponse,
    summary="Get a Question",
)
def get_question(
    question_id: UUID,
    response: Response,
    context: QuestionReadContext,
    session: DatabaseSession,
) -> QuestionResponse:
    question = QuestionService.get(session, context=context, question_id=question_id)
    response.headers["Cache-Control"] = "private, no-store"
    return question_response(question)


@router.patch(
    "/{question_id}",
    response_model=QuestionResponse,
    summary="Update an open Question",
)
def update_question(
    question_id: UUID,
    payload: UpdateQuestionRequest,
    response: Response,
    context: QuestionUpdateContext,
    session: DatabaseSession,
) -> QuestionResponse:
    question = QuestionService.update(
        session,
        context=context,
        question_id=question_id,
        request=payload,
    )
    response.headers["Cache-Control"] = "private, no-store"
    return question_response(question)


def _transition_question(
    *,
    question_id: UUID,
    payload: QuestionLifecycleRequest,
    response: Response,
    context: ExecutionContext,
    session: Session,
    target: QuestionStatus,
) -> QuestionResponse:
    question = QuestionService.transition(
        session,
        context=context,
        question_id=question_id,
        expected_version=payload.expected_version,
        target=target,
    )
    response.headers["Cache-Control"] = "private, no-store"
    return question_response(question)


@router.post(
    "/{question_id}/resolve",
    response_model=QuestionResponse,
    summary="Resolve a Question",
)
def resolve_question(
    question_id: UUID,
    payload: QuestionLifecycleRequest,
    response: Response,
    context: QuestionUpdateContext,
    session: DatabaseSession,
) -> QuestionResponse:
    return _transition_question(
        question_id=question_id,
        payload=payload,
        response=response,
        context=context,
        session=session,
        target=QuestionStatus.RESOLVED,
    )


@router.post(
    "/{question_id}/close",
    response_model=QuestionResponse,
    summary="Close a resolved Question",
)
def close_question(
    question_id: UUID,
    payload: QuestionLifecycleRequest,
    response: Response,
    context: QuestionUpdateContext,
    session: DatabaseSession,
) -> QuestionResponse:
    return _transition_question(
        question_id=question_id,
        payload=payload,
        response=response,
        context=context,
        session=session,
        target=QuestionStatus.CLOSED,
    )


@router.post(
    "/{question_id}/reopen",
    response_model=QuestionResponse,
    summary="Reopen a Question",
)
def reopen_question(
    question_id: UUID,
    payload: QuestionLifecycleRequest,
    response: Response,
    context: QuestionUpdateContext,
    session: DatabaseSession,
) -> QuestionResponse:
    return _transition_question(
        question_id=question_id,
        payload=payload,
        response=response,
        context=context,
        session=session,
        target=QuestionStatus.OPEN,
    )
