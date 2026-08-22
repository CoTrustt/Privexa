from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from privexa_api.ai_policy.contracts import AIProtectionProfileId


class ProtectionAction(StrEnum):
    TOKENIZE = "TOKENIZE"
    REPLACE = "REPLACE"
    MASK = "MASK"
    BLOCK = "BLOCK"


@dataclass(frozen=True, slots=True)
class DetectedEntity:
    """Raw-free detector output. Offsets refer to the request-local input string."""

    entity_type: str
    start: int
    end: int
    score: float
    recognizer_name: str | None = None


class ProtectionEntitySummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    entity_type: str = Field(min_length=1, max_length=64, pattern=r"^[A-Z][A-Z0-9_]*$")
    count: int = Field(ge=1)
    action: ProtectionAction


class ProtectionResult(BaseModel):
    """Protected provider-visible content plus safe, aggregate evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    protected_content: str = Field(min_length=1, repr=False)
    profile_id: AIProtectionProfileId
    protection_applied: bool
    entity_summaries: tuple[ProtectionEntitySummary, ...] = ()
    duration_ms: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_profile_state(self) -> Self:
        profile_selected = self.profile_id is not AIProtectionProfileId.NONE
        if self.protection_applied is not profile_selected:
            raise ValueError("protection state must match the selected profile")
        return self

    @property
    def detected_entity_count(self) -> int:
        return sum(summary.count for summary in self.entity_summaries)
