from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from privexa_api.access_control.permissions import AuthorizationScope, Permission
from privexa_api.ai_types import AITaskType
from privexa_api.security.enums import SensitivityLevel
from privexa_api.security.execution_context import ExecutionContext


class AIPolicyOutcome(StrEnum):
    ALLOW = "ALLOW"
    DENY = "DENY"


class AIPolicyReasonCode(StrEnum):
    ALLOWED = "AI_POLICY_ALLOWED"
    UNKNOWN_TASK = "AI_POLICY_UNKNOWN_TASK"
    INVALID_CONTEXT = "AI_POLICY_INVALID_CONTEXT"
    UNKNOWN_SENSITIVITY = "AI_POLICY_UNKNOWN_SENSITIVITY"
    FEATURE_DISABLED = "AI_POLICY_FEATURE_DISABLED"
    GLOBAL_DISABLED = "AI_POLICY_GLOBAL_DISABLED"
    TASK_DISABLED = "AI_POLICY_TASK_DISABLED"
    TENANT_RESTRICTED = "AI_POLICY_TENANT_RESTRICTED"
    NO_APPLICABLE_RULE = "AI_POLICY_NO_APPLICABLE_RULE"
    AUTHORITY_DENIED = "AI_POLICY_AUTHORITY_DENIED"
    BUDGET_EXCEEDED = "AI_POLICY_BUDGET_EXCEEDED"
    CONFIGURATION_INVALID = "AI_POLICY_CONFIGURATION_INVALID"
    PROVIDER_CLASS_UNAVAILABLE = "AI_POLICY_PROVIDER_CLASS_UNAVAILABLE"
    MODEL_CLASS_UNAVAILABLE = "AI_POLICY_MODEL_CLASS_UNAVAILABLE"
    REDACTION_REQUIRED = "AI_POLICY_REDACTION_REQUIRED"
    NO_COMPLIANT_ROUTE = "AI_POLICY_NO_COMPLIANT_ROUTE"


class AIProviderClass(StrEnum):
    ENTERPRISE_APPROVED = "ENTERPRISE_APPROVED"
    ZDR_APPROVED = "ZDR_APPROVED"
    INTERNAL_ONLY = "INTERNAL_ONLY"


class AIModelClass(StrEnum):
    GENERAL_APPROVED = "GENERAL_APPROVED"
    RESTRICTED_DATA_APPROVED = "RESTRICTED_DATA_APPROVED"


class ZDRRequirement(StrEnum):
    NOT_REQUIRED = "NOT_REQUIRED"
    REQUIRED = "REQUIRED"


class RedactionRequirement(StrEnum):
    NOT_REQUIRED = "NOT_REQUIRED"
    REQUIRED = "REQUIRED"


class AIProtectionProfileId(StrEnum):
    NONE = "NONE"
    EXTERNAL_MODEL_PII_V1 = "EXTERNAL_MODEL_PII_V1"

    @property
    def restrictiveness(self) -> int:
        return {
            AIProtectionProfileId.NONE: 0,
            AIProtectionProfileId.EXTERNAL_MODEL_PII_V1: 10,
        }[self]


class AIFallbackPolicy(StrEnum):
    NO_FALLBACK = "NO_FALLBACK"
    SAME_SECURITY_CLASS_ONLY = "SAME_SECURITY_CLASS_ONLY"

    @property
    def restrictiveness(self) -> int:
        return {
            AIFallbackPolicy.SAME_SECURITY_CLASS_ONLY: 10,
            AIFallbackPolicy.NO_FALLBACK: 20,
        }[self]


class AgentAuthority(StrEnum):
    READ_AUTHORISED_CONTEXT = "READ_AUTHORISED_CONTEXT"
    PREPARE_PROPOSED_OUTPUT = "PREPARE_PROPOSED_OUTPUT"
    AUTHORITATIVE_DATABASE_MUTATION = "AUTHORITATIVE_DATABASE_MUTATION"
    EXTERNAL_COMMUNICATION = "EXTERNAL_COMMUNICATION"
    APPROVAL = "APPROVAL"
    SIGN_OFF = "SIGN_OFF"
    CROSS_CLIENT_DATA_MOVEMENT = "CROSS_CLIENT_DATA_MOVEMENT"
    DESTRUCTIVE_ACTION = "DESTRUCTIVE_ACTION"
    PERMISSION_CHANGE = "PERMISSION_CHANGE"


BUILD0_AGENT_AUTHORITY_CEILING = frozenset(
    {
        AgentAuthority.READ_AUTHORISED_CONTEXT,
        AgentAuthority.PREPARE_PROPOSED_OUTPUT,
    }
)


class AIPolicyConstraints(BaseModel):
    """One restrictive overlay. Missing fields do not relax another rule."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    enabled: bool | None = None
    allowed_provider_classes: frozenset[AIProviderClass] | None = None
    allowed_model_classes: frozenset[AIModelClass] | None = None
    zdr_requirement: ZDRRequirement | None = None
    redaction_requirement: RedactionRequirement | None = None
    protection_profile: AIProtectionProfileId | None = None
    max_input_tokens: int | None = Field(default=None, ge=1)
    max_output_tokens: int | None = Field(default=None, ge=1)
    max_cost_usd: Decimal | None = Field(default=None, gt=0)
    timeout_seconds: float | None = Field(default=None, gt=0)
    fallback_policy: AIFallbackPolicy | None = None
    allowed_agent_authorities: frozenset[AgentAuthority] | None = None

    @model_validator(mode="after")
    def reject_empty_execution_sets(self) -> Self:
        if self.allowed_provider_classes is not None and not self.allowed_provider_classes:
            raise ValueError("policy provider class set must not be empty")
        if self.allowed_model_classes is not None and not self.allowed_model_classes:
            raise ValueError("policy model class set must not be empty")
        return self


class AIPolicyRule(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    rule_id: str = Field(min_length=1, max_length=128, pattern=r"^[a-z0-9_.:-]+$")
    revision: int = Field(ge=1)
    task: AITaskType | None = None
    sensitivity: SensitivityLevel | None = None
    firm_id: UUID | None = None
    client_id: UUID | None = None
    constraints: AIPolicyConstraints
    content_hash: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_tenant_scope(self) -> Self:
        if self.client_id is not None and self.firm_id is None:
            raise ValueError("client policy rule requires firm_id")
        return self


class AIPolicyRuleReference(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    rule_id: str = Field(min_length=1, max_length=128)
    revision: int = Field(ge=1)
    content_hash: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")


class AIPolicyEvaluationRequest(BaseModel):
    """Internal policy request assembled by the Gateway from trusted application state."""

    model_config = ConfigDict(
        arbitrary_types_allowed=True,
        extra="forbid",
        frozen=True,
        strict=True,
    )

    context: ExecutionContext
    task: AITaskType
    task_version: str | None = Field(default=None, max_length=32)
    required_scope: AuthorizationScope | None = None
    required_permission: Permission | None = None
    requested_agent_authorities: frozenset[AgentAuthority] = frozenset()
    requested_max_output_tokens: int | None = Field(default=None, ge=1)
    requested_timeout_seconds: float | None = Field(default=None, gt=0)


class EffectiveAIPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    allowed_provider_classes: frozenset[AIProviderClass] = Field(min_length=1)
    allowed_model_classes: frozenset[AIModelClass] = Field(min_length=1)
    zdr_requirement: ZDRRequirement
    redaction_requirement: RedactionRequirement
    protection_profile: AIProtectionProfileId
    max_input_tokens: int = Field(ge=1)
    max_output_tokens: int = Field(ge=1)
    max_cost_usd: Decimal = Field(gt=0)
    timeout_seconds: float = Field(gt=0)
    fallback_policy: AIFallbackPolicy
    allowed_agent_authorities: frozenset[AgentAuthority]

    @model_validator(mode="after")
    def require_profile_for_mandatory_protection(self) -> Self:
        if (
            self.redaction_requirement is RedactionRequirement.REQUIRED
            and self.protection_profile is AIProtectionProfileId.NONE
        ):
            raise ValueError("required redaction must select a protection profile")
        return self


class AIPolicyDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    decision_id: UUID
    decision: AIPolicyOutcome
    reason_code: AIPolicyReasonCode
    policy_version: str = Field(min_length=1, max_length=128)
    policy_hash: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    decision_fingerprint: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
    )
    evaluated_at: datetime
    task: AITaskType | None
    task_version: str | None = Field(default=None, max_length=32)
    firm_id: UUID | None
    client_id: UUID | None
    sensitivity: SensitivityLevel | None
    rule_references: tuple[AIPolicyRuleReference, ...] = ()
    effective_policy: EffectiveAIPolicy | None = None

    @model_validator(mode="after")
    def validate_decision_shape(self) -> Self:
        if self.decision is AIPolicyOutcome.ALLOW:
            if self.reason_code is not AIPolicyReasonCode.ALLOWED or self.effective_policy is None:
                raise ValueError("ALLOW decision requires allowed reason and effective policy")
        elif self.effective_policy is not None:
            raise ValueError("DENY decision must not carry an effective execution policy")
        return self

    @property
    def is_allowed(self) -> bool:
        return self.decision is AIPolicyOutcome.ALLOW


class AIPolicyRuntimeSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    global_enabled: bool | None
    task_enabled: bool | None
    control_references: tuple[AIPolicyRuleReference, ...] = ()
    override_rules: tuple[AIPolicyRule, ...] = ()
