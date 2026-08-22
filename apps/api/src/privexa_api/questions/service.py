from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from privexa_api.access_control.permissions import Permission
from privexa_api.db.session import record_domain_event
from privexa_api.db.tenant_scope import require_matching_execution_context_scope
from privexa_api.domain.errors import DomainResourceNotFoundError
from privexa_api.observability.tracing import domain_span
from privexa_api.questions.domain import (
    require_content_mutable,
    require_transition,
    validate_context,
    validate_question_text,
    validate_title,
)
from privexa_api.questions.enums import QuestionStatus
from privexa_api.questions.models import Question
from privexa_api.questions.repository import QuestionPage, QuestionRepository
from privexa_api.questions.schemas import CreateQuestionRequest, UpdateQuestionRequest
from privexa_api.security.execution_context import (
    ExecutionContext,
    require_trusted_execution_context,
)
from privexa_api.security.professional_records import (
    ProfessionalRecordAuthority,
    ProfessionalRecordOperation,
    issue_professional_record_authority,
)


def _span_attributes(context: ExecutionContext, operation: str) -> dict[str, object]:
    return {
        "domain.object_type": "Question",
        "domain.operation": operation,
        "request.id": context.request_id,
        "trace.id": context.trace_id,
        "tenant.firm_id": context.firm_id,
        "tenant.client_id": context.client_id,
    }


class QuestionService:
    @staticmethod
    def _context(
        session: Session,
        context: ExecutionContext,
        permission: Permission,
    ) -> ExecutionContext:
        trusted = require_trusted_execution_context(context)
        trusted.require_capability(permission)
        require_matching_execution_context_scope(session, trusted)
        return trusted

    @staticmethod
    def _authority(
        session: Session,
        context: ExecutionContext,
        *,
        permission: Permission,
        operation: ProfessionalRecordOperation,
    ) -> ProfessionalRecordAuthority:
        trusted = QuestionService._context(session, context, permission)
        return issue_professional_record_authority(
            trusted,
            capability=permission,
            operation=operation,
        )

    @staticmethod
    def _get_or_raise(
        session: Session,
        *,
        context: ExecutionContext,
        question_id: UUID,
    ) -> Question:
        question = QuestionRepository.get(
            session,
            context=context.to_client_context(),
            question_id=question_id,
        )
        if question is None:
            raise DomainResourceNotFoundError()
        return question

    @staticmethod
    def create(
        session: Session,
        *,
        context: ExecutionContext,
        request: CreateQuestionRequest,
    ) -> Question:
        authority = QuestionService._authority(
            session,
            context,
            permission=Permission.QUESTION_CREATE,
            operation=ProfessionalRecordOperation.CREATE,
        )
        with domain_span(
            "domain.question.create",
            attributes=_span_attributes(context, "create"),
        ):
            question = Question(
                id=uuid4(),
                **authority.creation_values(),
                title=validate_title(request.title),
                question_text=validate_question_text(request.question_text),
                context=validate_context(request.context),
                status=QuestionStatus.OPEN,
            )
            QuestionRepository.add(session, question=question)
            record_domain_event(
                session,
                authority.event(
                    event_type="question.created",
                    aggregate_type="Question",
                    aggregate_id=question.id,
                    payload={"status": question.status.value, "version": question.version},
                ),
            )
            return question

    @staticmethod
    def get(
        session: Session,
        *,
        context: ExecutionContext,
        question_id: UUID,
    ) -> Question:
        trusted = QuestionService._context(session, context, Permission.QUESTION_READ)
        with domain_span(
            "domain.question.get",
            attributes=_span_attributes(trusted, "get"),
        ):
            return QuestionService._get_or_raise(
                session,
                context=trusted,
                question_id=question_id,
            )

    @staticmethod
    def list(
        session: Session,
        *,
        context: ExecutionContext,
        limit: int,
        offset: int,
        status: QuestionStatus | None,
    ) -> QuestionPage:
        trusted = QuestionService._context(session, context, Permission.QUESTION_READ)
        with domain_span(
            "domain.question.list",
            attributes=_span_attributes(trusted, "list"),
        ):
            return QuestionRepository.list(
                session,
                context=trusted.to_client_context(),
                limit=limit,
                offset=offset,
                status=status,
            )

    @staticmethod
    def update(
        session: Session,
        *,
        context: ExecutionContext,
        question_id: UUID,
        request: UpdateQuestionRequest,
    ) -> Question:
        authority = QuestionService._authority(
            session,
            context,
            permission=Permission.QUESTION_UPDATE,
            operation=ProfessionalRecordOperation.UPDATE,
        )
        with domain_span(
            "domain.question.update",
            attributes=_span_attributes(context, "update"),
        ):
            question = QuestionService._get_or_raise(
                session,
                context=context,
                question_id=question_id,
            )
            authority.require_record(question, expected_version=request.expected_version)
            require_content_mutable(question.status)

            changed_fields: list[str] = []
            if "title" in request.model_fields_set:
                value = validate_title(request.title)
                if question.title != value:
                    question.title = value
                    changed_fields.append("title")
            if "question_text" in request.model_fields_set:
                value = validate_question_text(request.question_text)
                if question.question_text != value:
                    question.question_text = value
                    changed_fields.append("question_text")
            if "context" in request.model_fields_set:
                value = validate_context(request.context)
                if question.context != value:
                    question.context = value
                    changed_fields.append("context")

            if not changed_fields:
                return question
            values = authority.update_values(question, expected_version=request.expected_version)
            question.updated_by_membership_id = values["updated_by_membership_id"]
            QuestionRepository.flush(session)
            record_domain_event(
                session,
                authority.event(
                    event_type="question.updated",
                    aggregate_type="Question",
                    aggregate_id=question.id,
                    payload={"fields": sorted(changed_fields), "version": question.version},
                ),
            )
            return question

    @staticmethod
    def transition(
        session: Session,
        *,
        context: ExecutionContext,
        question_id: UUID,
        expected_version: int,
        target: QuestionStatus,
    ) -> Question:
        authority = QuestionService._authority(
            session,
            context,
            permission=Permission.QUESTION_UPDATE,
            operation=ProfessionalRecordOperation.UPDATE,
        )
        operation = {
            QuestionStatus.OPEN: "reopen",
            QuestionStatus.RESOLVED: "resolve",
            QuestionStatus.CLOSED: "close",
        }[target]
        with domain_span(
            f"domain.question.{operation}",
            attributes=_span_attributes(context, operation),
        ):
            question = QuestionService._get_or_raise(
                session,
                context=context,
                question_id=question_id,
            )
            authority.require_record(question, expected_version=expected_version)
            if question.status is target:
                return question
            previous = question.status
            require_transition(previous, target)
            values = authority.update_values(question, expected_version=expected_version)
            question.status = target
            question.updated_by_membership_id = values["updated_by_membership_id"]
            QuestionRepository.flush(session)
            event_type = {
                QuestionStatus.OPEN: "question.reopened",
                QuestionStatus.RESOLVED: "question.resolved",
                QuestionStatus.CLOSED: "question.closed",
            }[target]
            record_domain_event(
                session,
                authority.event(
                    event_type=event_type,
                    aggregate_type="Question",
                    aggregate_id=question.id,
                    payload={
                        "previous_status": previous.value,
                        "status": target.value,
                        "version": question.version,
                    },
                ),
            )
            return question
