from __future__ import annotations

from privexa_api.domain.errors import DomainLifecycleConflictError, DomainValidationError
from privexa_api.domain.lifecycle import LifecyclePolicy
from privexa_api.questions.enums import QuestionStatus

TITLE_MAX_LENGTH = 255
QUESTION_TEXT_MAX_LENGTH = 20_000
CONTEXT_MAX_LENGTH = 50_000

QUESTION_LIFECYCLE = LifecyclePolicy(
    allowed_transitions={
        QuestionStatus.OPEN: {QuestionStatus.RESOLVED},
        QuestionStatus.RESOLVED: {QuestionStatus.OPEN, QuestionStatus.CLOSED},
        QuestionStatus.CLOSED: {QuestionStatus.OPEN},
    }
)


def _require_authored_text(
    value: object,
    *,
    maximum_length: int,
    code: str,
) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum_length:
        raise DomainValidationError(code=code)
    return value


def validate_title(value: object) -> str:
    return _require_authored_text(
        value,
        maximum_length=TITLE_MAX_LENGTH,
        code="QUESTION_TITLE_INVALID",
    )


def validate_question_text(value: object) -> str:
    return _require_authored_text(
        value,
        maximum_length=QUESTION_TEXT_MAX_LENGTH,
        code="QUESTION_TEXT_INVALID",
    )


def validate_context(value: object | None) -> str | None:
    if value is None:
        return None
    return _require_authored_text(
        value,
        maximum_length=CONTEXT_MAX_LENGTH,
        code="QUESTION_CONTEXT_INVALID",
    )


def require_content_mutable(status: QuestionStatus) -> None:
    if status is not QuestionStatus.OPEN:
        raise DomainLifecycleConflictError()


def require_transition(current: QuestionStatus, target: QuestionStatus) -> None:
    if current is target:
        return
    QUESTION_LIFECYCLE.require(current, target)
