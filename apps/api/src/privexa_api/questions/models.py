from __future__ import annotations

from uuid import UUID

from sqlalchemy import CheckConstraint, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from privexa_api.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from privexa_api.db.professional import (
    ActorProvenanceMixin,
    ClientOwnedMixin,
    VersionedMixin,
    professional_object_constraints,
)
from privexa_api.db.types import constrained_enum
from privexa_api.questions.enums import QuestionStatus


class Question(
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    ClientOwnedMixin,
    ActorProvenanceMixin,
    VersionedMixin,
    Base,
):
    """Authoritative human-authored question within one client workspace."""

    __tablename__ = "questions"
    __table_args__ = (
        *professional_object_constraints(__tablename__),
        CheckConstraint(
            "status IN ('OPEN', 'RESOLVED', 'CLOSED')",
            name="question_status",
        ),
        CheckConstraint(
            "char_length(title) BETWEEN 1 AND 255 AND title ~ '[^[:space:]]'",
            name="question_title_valid",
        ),
        CheckConstraint(
            "char_length(question_text) BETWEEN 1 AND 20000 AND question_text ~ '[^[:space:]]'",
            name="question_text_valid",
        ),
        CheckConstraint(
            "context IS NULL OR (char_length(context) BETWEEN 1 AND 50000 "
            "AND context ~ '[^[:space:]]')",
            name="question_context_valid",
        ),
        Index(
            "ix_questions_firm_client_status_created_id",
            "firm_id",
            "client_id",
            "status",
            "created_at",
            "id",
        ),
    )

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    context: Mapped[str | None] = mapped_column(Text)
    status: Mapped[QuestionStatus] = mapped_column(
        constrained_enum(QuestionStatus, name="question_status"),
        nullable=False,
        default=QuestionStatus.OPEN,
        server_default=QuestionStatus.OPEN.value,
    )

    # Redeclarations keep type checkers aware of inherited concrete ownership/provenance fields.
    firm_id: Mapped[UUID]
    client_id: Mapped[UUID]
    created_by_membership_id: Mapped[UUID]
    updated_by_membership_id: Mapped[UUID]
