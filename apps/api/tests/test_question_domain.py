from __future__ import annotations

import pytest

from privexa_api.domain.errors import DomainLifecycleConflictError, DomainValidationError
from privexa_api.questions.domain import (
    require_content_mutable,
    require_transition,
    validate_context,
    validate_question_text,
    validate_title,
)
from privexa_api.questions.enums import QuestionStatus


def test_authored_content_is_preserved_exactly() -> None:
    title = "  क्या धारा 8(7) लागू होती है?  "
    question_text = (
        "क्या DPDP Act, 2023 की धारा 8(7) लागू होती है?\nReference: https://www.meity.gov.in/"
    )
    context = "Client term: ‘Applicant Pool’\nRetention proposed: 24 months."

    assert validate_title(title) == title
    assert validate_question_text(question_text) == question_text
    assert validate_context(context) == context
    assert validate_context(None) is None


@pytest.mark.parametrize(
    ("validator", "value", "code"),
    [
        (validate_title, " \t\n", "QUESTION_TITLE_INVALID"),
        (validate_title, "x" * 256, "QUESTION_TITLE_INVALID"),
        (validate_question_text, "\n\t", "QUESTION_TEXT_INVALID"),
        (validate_question_text, "x" * 20_001, "QUESTION_TEXT_INVALID"),
        (validate_context, "  ", "QUESTION_CONTEXT_INVALID"),
        (validate_context, "x" * 50_001, "QUESTION_CONTEXT_INVALID"),
    ],
)
def test_invalid_authored_content_is_rejected(validator, value: str, code: str) -> None:
    with pytest.raises(DomainValidationError, match=code):
        validator(value)


@pytest.mark.parametrize(
    ("current", "target", "allowed"),
    [
        (QuestionStatus.OPEN, QuestionStatus.OPEN, True),
        (QuestionStatus.OPEN, QuestionStatus.RESOLVED, True),
        (QuestionStatus.OPEN, QuestionStatus.CLOSED, False),
        (QuestionStatus.RESOLVED, QuestionStatus.OPEN, True),
        (QuestionStatus.RESOLVED, QuestionStatus.RESOLVED, True),
        (QuestionStatus.RESOLVED, QuestionStatus.CLOSED, True),
        (QuestionStatus.CLOSED, QuestionStatus.OPEN, True),
        (QuestionStatus.CLOSED, QuestionStatus.RESOLVED, False),
        (QuestionStatus.CLOSED, QuestionStatus.CLOSED, True),
    ],
)
def test_complete_lifecycle_matrix(
    current: QuestionStatus,
    target: QuestionStatus,
    allowed: bool,
) -> None:
    if allowed:
        require_transition(current, target)
    else:
        with pytest.raises(DomainLifecycleConflictError):
            require_transition(current, target)


def test_content_is_mutable_only_while_open() -> None:
    require_content_mutable(QuestionStatus.OPEN)
    for status in (QuestionStatus.RESOLVED, QuestionStatus.CLOSED):
        with pytest.raises(DomainLifecycleConflictError):
            require_content_mutable(status)
