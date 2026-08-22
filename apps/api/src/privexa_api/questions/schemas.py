from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from privexa_api.questions.domain import (
    CONTEXT_MAX_LENGTH,
    QUESTION_TEXT_MAX_LENGTH,
    TITLE_MAX_LENGTH,
)
from privexa_api.questions.enums import QuestionStatus
from privexa_api.questions.models import Question

TitleValue = Annotated[str, StringConstraints(min_length=1, max_length=TITLE_MAX_LENGTH)]
QuestionTextValue = Annotated[
    str,
    StringConstraints(min_length=1, max_length=QUESTION_TEXT_MAX_LENGTH),
]
ContextValue = Annotated[
    str,
    StringConstraints(min_length=1, max_length=CONTEXT_MAX_LENGTH),
]


def _not_blank(value: str) -> str:
    if not value.strip():
        raise ValueError("authored text must not be blank")
    return value


class CreateQuestionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    title: TitleValue
    question_text: QuestionTextValue
    context: ContextValue | None = None

    @field_validator("title", "question_text", "context")
    @classmethod
    def reject_blank_authored_text(cls, value: str | None) -> str | None:
        return None if value is None else _not_blank(value)


class UpdateQuestionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    expected_version: int = Field(ge=1)
    title: TitleValue | None = None
    question_text: QuestionTextValue | None = None
    context: ContextValue | None = None

    @field_validator("title", "question_text", "context")
    @classmethod
    def reject_blank_authored_text(cls, value: str | None) -> str | None:
        return None if value is None else _not_blank(value)

    @model_validator(mode="after")
    def require_mutation(self) -> UpdateQuestionRequest:
        mutable = self.model_fields_set & {"title", "question_text", "context"}
        if not mutable:
            raise ValueError("at least one mutable field is required")
        if "title" in self.model_fields_set and self.title is None:
            raise ValueError("title cannot be null")
        if "question_text" in self.model_fields_set and self.question_text is None:
            raise ValueError("question_text cannot be null")
        return self


class QuestionLifecycleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    expected_version: int = Field(ge=1)


class QuestionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)

    id: UUID
    client_id: UUID
    title: str
    question_text: str
    context: str | None
    status: QuestionStatus
    version: int
    created_by_membership_id: UUID
    updated_by_membership_id: UUID
    created_at: datetime
    updated_at: datetime


class QuestionPageMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    limit: int
    offset: int
    has_more: bool


class QuestionListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    items: tuple[QuestionResponse, ...]
    page: QuestionPageMetadata


def question_response(question: Question) -> QuestionResponse:
    return QuestionResponse.model_validate(question)
