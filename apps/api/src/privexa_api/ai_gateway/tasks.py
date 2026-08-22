from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType

from pydantic import BaseModel, ConfigDict, Field

from privexa_api.access_control.permissions import AuthorizationScope, Permission
from privexa_api.ai_gateway.contracts import AIModelAlias, AITaskType
from privexa_api.ai_gateway.errors import AIErrorCategory, AIPolicyViolation
from privexa_api.ai_gateway.prompts import (
    PREPARE_WORK_NOTE_PROMPT,
    SYNTHETIC_TEXT_SUMMARY_PROMPT,
    AIPromptTemplate,
)
from privexa_api.ai_policy.contracts import AgentAuthority


class SyntheticTextSummaryInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    text: str = Field(min_length=1, max_length=2_000)


class SyntheticTextSummaryResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    summary: str = Field(min_length=1, max_length=500)


class PrepareWorkNoteInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    note: str = Field(min_length=1, max_length=5_000)


class PrepareWorkNoteResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    draft: str = Field(min_length=1, max_length=1_800)
    suggested_follow_up: str = Field(min_length=1, max_length=600)
    caveat: str | None = Field(default=None, max_length=600)


class AIExecutionConstraints(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    max_input_characters: int = Field(ge=1)
    max_input_tokens: int = Field(ge=1)
    max_output_tokens: int = Field(ge=1)
    timeout_seconds: float = Field(gt=0)


@dataclass(frozen=True, slots=True)
class AITaskDefinition:
    task: AITaskType
    version: str
    input_model: type[BaseModel]
    output_model: type[BaseModel]
    prompt: AIPromptTemplate
    user_content: Callable[[BaseModel], str]
    required_scope: AuthorizationScope
    required_permission: Permission
    model_alias: AIModelAlias
    constraints: AIExecutionConstraints
    requested_agent_authorities: frozenset[AgentAuthority]
    allowed_source_types: frozenset[str] = frozenset()


def _synthetic_user_content(value: BaseModel) -> str:
    if not isinstance(value, SyntheticTextSummaryInput):
        raise AIPolicyViolation(AIErrorCategory.INVALID_INPUT)
    return value.text


def _work_note_user_content(value: BaseModel) -> str:
    if not isinstance(value, PrepareWorkNoteInput):
        raise AIPolicyViolation(AIErrorCategory.INVALID_INPUT)
    return value.note


SYNTHETIC_TEXT_SUMMARY_TASK = AITaskDefinition(
    task=AITaskType.SYNTHETIC_TEXT_SUMMARY,
    version="1",
    input_model=SyntheticTextSummaryInput,
    output_model=SyntheticTextSummaryResult,
    prompt=SYNTHETIC_TEXT_SUMMARY_PROMPT,
    user_content=_synthetic_user_content,
    required_scope=AuthorizationScope.CLIENT,
    required_permission=Permission.CLIENT_READ,
    model_alias=AIModelAlias.FAST_GENERAL_V1,
    constraints=AIExecutionConstraints(
        max_input_characters=2_000,
        max_input_tokens=4_096,
        max_output_tokens=128,
        timeout_seconds=20.0,
    ),
    requested_agent_authorities=frozenset(
        {
            AgentAuthority.READ_AUTHORISED_CONTEXT,
            AgentAuthority.PREPARE_PROPOSED_OUTPUT,
        }
    ),
)

PREPARE_WORK_NOTE_TASK = AITaskDefinition(
    task=AITaskType.PREPARE_WORK_NOTE,
    version="1",
    input_model=PrepareWorkNoteInput,
    output_model=PrepareWorkNoteResult,
    prompt=PREPARE_WORK_NOTE_PROMPT,
    user_content=_work_note_user_content,
    required_scope=AuthorizationScope.CLIENT,
    required_permission=Permission.FILE_READ,
    model_alias=AIModelAlias.PROTECTED_GENERAL_V1,
    constraints=AIExecutionConstraints(
        max_input_characters=5_000,
        max_input_tokens=1_500,
        max_output_tokens=400,
        timeout_seconds=20.0,
    ),
    requested_agent_authorities=frozenset(
        {
            AgentAuthority.READ_AUTHORISED_CONTEXT,
            AgentAuthority.PREPARE_PROPOSED_OUTPUT,
        }
    ),
    allowed_source_types=frozenset({"stored_file"}),
)


class AITaskRegistry:
    def __init__(self, definitions: Mapping[AITaskType, AITaskDefinition]) -> None:
        if not definitions:
            raise ValueError("at least one AI task definition is required")
        if any(key is not definition.task for key, definition in definitions.items()):
            raise ValueError("AI task registry keys must match their definitions")
        self._definitions = MappingProxyType(dict(definitions))

    def resolve(self, task: AITaskType) -> AITaskDefinition:
        definition = self.find(task)
        if definition is None:
            raise AIPolicyViolation(AIErrorCategory.UNSUPPORTED_TASK)
        return definition

    def find(self, task: object) -> AITaskDefinition | None:
        return self._definitions.get(task) if isinstance(task, AITaskType) else None


def build_task_registry() -> AITaskRegistry:
    return AITaskRegistry(
        {
            AITaskType.SYNTHETIC_TEXT_SUMMARY: SYNTHETIC_TEXT_SUMMARY_TASK,
            AITaskType.PREPARE_WORK_NOTE: PREPARE_WORK_NOTE_TASK,
        }
    )
