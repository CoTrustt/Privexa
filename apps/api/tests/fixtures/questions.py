from __future__ import annotations

from uuid import UUID, uuid4

from privexa_api.questions.enums import QuestionStatus
from privexa_api.questions.models import Question


def question_record(
    *,
    firm_id: UUID,
    client_id: UUID,
    membership_id: UUID,
    question_id: UUID | None = None,
    title: str = "What retention period applies?",
    question_text: str = "How long may the client retain this category of personal data?",
    context: str | None = None,
    status: QuestionStatus = QuestionStatus.OPEN,
) -> Question:
    return Question(
        id=question_id or uuid4(),
        firm_id=firm_id,
        client_id=client_id,
        created_by_membership_id=membership_id,
        updated_by_membership_id=membership_id,
        title=title,
        question_text=question_text,
        context=context,
        status=status,
    )
