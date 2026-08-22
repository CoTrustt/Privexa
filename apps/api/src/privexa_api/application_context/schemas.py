from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ApplicationContextState(StrEnum):
    ACTIVE_CLIENT = "ACTIVE_CLIENT"
    CLIENT_SELECTION_REQUIRED = "CLIENT_SELECTION_REQUIRED"
    NO_AUTHORISED_CLIENTS = "NO_AUTHORISED_CLIENTS"


class UserSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID
    display_name: str


class FirmSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID
    display_name: str


class ClientSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID
    display_name: str


class QuestionCapabilities(BaseModel):
    """Browser guidance only; every operation remains server-authorized."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    can_create: bool
    can_update: bool


class ApplicationContextResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, use_enum_values=True)

    state: ApplicationContextState
    user: UserSummary
    firm: FirmSummary
    active_client: ClientSummary | None
    authorised_clients: list[ClientSummary]
    question_capabilities: QuestionCapabilities


class ActiveClientResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    active_client: ClientSummary
