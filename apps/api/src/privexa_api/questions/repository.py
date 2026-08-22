from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from privexa_api.access_control.context import ClientContext
from privexa_api.questions.enums import QuestionStatus
from privexa_api.questions.models import Question


@dataclass(frozen=True, slots=True)
class QuestionPage:
    items: tuple[Question, ...]
    has_more: bool


class QuestionRepository:
    @staticmethod
    def add(session: Session, *, question: Question) -> Question:
        session.add(question)
        session.flush()
        return question

    @staticmethod
    def get(
        session: Session,
        *,
        context: ClientContext,
        question_id: UUID,
    ) -> Question | None:
        statement = select(Question).where(
            Question.id == question_id,
            Question.firm_id == context.firm_id,
            Question.client_id == context.client_id,
        )
        return session.scalar(statement)

    @staticmethod
    def list(
        session: Session,
        *,
        context: ClientContext,
        limit: int,
        offset: int,
        status: QuestionStatus | None,
    ) -> QuestionPage:
        statement: Select[tuple[Question]] = select(Question).where(
            Question.firm_id == context.firm_id,
            Question.client_id == context.client_id,
        )
        if status is not None:
            statement = statement.where(Question.status == status)
        statement = statement.order_by(Question.created_at.desc(), Question.id.desc())
        rows = tuple(session.scalars(statement.offset(offset).limit(limit + 1)))
        return QuestionPage(items=rows[:limit], has_more=len(rows) > limit)

    @staticmethod
    def flush(session: Session) -> None:
        session.flush()
