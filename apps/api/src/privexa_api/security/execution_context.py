from __future__ import annotations

import json
import logging
from typing import Annotated, Any, Self
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PrivateAttr,
    StringConstraints,
    field_serializer,
    model_validator,
)

from privexa_api.access_control.context import (
    AuthorizationContext,
    ClientAuthorizationContext,
    ClientContext,
    FirmAuthorizationContext,
    FirmContext,
    SelfAuthorizationContext,
)
from privexa_api.access_control.decisions import AuthorizationFailureReason
from privexa_api.access_control.enums import FirmRole
from privexa_api.access_control.errors import AuthorizationDeniedError
from privexa_api.access_control.permissions import (
    AuthorizationScope,
    Permission,
    permission_scope,
)
from privexa_api.security.enums import OriginatingChannel, SensitivityLevel
from privexa_api.security.errors import SensitivityFailureReason, SensitivityPolicyViolation
from privexa_api.security.sensitivity import SensitivityPolicy

TraceId = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{32}$")]

_TRUSTED_EXECUTION_CONTEXT = object()
LOGGER = logging.getLogger("privexa.sensitivity")
_SENSITIVITY_HANDLER_NAME = "privexa-sensitivity-json"


def configure_sensitivity_logging() -> None:
    LOGGER.disabled = False
    LOGGER.setLevel(logging.INFO)
    LOGGER.propagate = False
    if not any(handler.get_name() == _SENSITIVITY_HANDLER_NAME for handler in LOGGER.handlers):
        handler = logging.StreamHandler()
        handler.set_name(_SENSITIVITY_HANDLER_NAME)
        handler.setFormatter(logging.Formatter("%(message)s"))
        LOGGER.addHandler(handler)


class ExecutionContext(BaseModel):
    """Immutable authority envelope for one server-validated operation.

    Authoritative instances must be issued from an AccessControlService authorization result.
    Raw request data, serialized contexts, LLM output, and worker payloads are never trusted
    construction inputs. Do not add secrets, tokens, ORM objects, or unproven authority fields.
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        validate_default=True,
    )

    request_id: UUID
    trace_id: TraceId | None
    user_id: UUID
    membership_id: UUID
    firm_id: UUID
    client_id: UUID | None
    firm_role: FirmRole
    authorization_scope: AuthorizationScope
    granted_capabilities: frozenset[Permission] = Field(min_length=1)
    effective_sensitivity: SensitivityLevel
    originating_channel: OriginatingChannel

    _issuance_marker: object | None = PrivateAttr(default=None)

    @model_validator(mode="after")
    def validate_authority_scope(self) -> Self:
        if self.trace_id == "0" * 32:
            raise ValueError("trace_id must identify a valid non-zero trace")
        if self.authorization_scope == AuthorizationScope.CLIENT:
            if self.client_id is None:
                raise ValueError("client-scoped execution requires client_id")
        elif self.client_id is not None:
            raise ValueError("firm and self execution cannot carry client_id")

        if any(
            permission_scope(capability) != self.authorization_scope
            for capability in self.granted_capabilities
        ):
            raise ValueError("granted capabilities must match the authorization scope")
        return self

    @field_serializer("granted_capabilities", when_used="json")
    def serialize_capabilities(
        self,
        capabilities: frozenset[Permission],
    ) -> list[str]:
        return sorted(capability.value for capability in capabilities)

    def model_copy(
        self,
        *,
        update: dict[str, Any] | None = None,
        deep: bool = False,
    ) -> Self:
        if update:
            raise TypeError("ExecutionContext cannot be copied with authority updates")
        return super().model_copy(deep=deep)

    def has_capability(self, capability: Permission) -> bool:
        return (
            self._issuance_marker is _TRUSTED_EXECUTION_CONTEXT
            and isinstance(capability, Permission)
            and capability in self.granted_capabilities
        )

    def require_capability(self, capability: Permission) -> None:
        if self._issuance_marker is not _TRUSTED_EXECUTION_CONTEXT:
            raise AuthorizationDeniedError(
                reason=AuthorizationFailureReason.INVALID_CONTEXT,
                permission=capability if isinstance(capability, Permission) else None,
            )
        if not isinstance(capability, Permission) or capability not in self.granted_capabilities:
            raise AuthorizationDeniedError(
                reason=AuthorizationFailureReason.PERMISSION_DENIED,
                permission=capability if isinstance(capability, Permission) else None,
            )

    def with_minimum_sensitivity(
        self,
        *minimums: SensitivityLevel,
    ) -> ExecutionContext:
        """Return a trusted immutable context at least as restrictive as every minimum."""

        self._require_trusted()
        if not minimums:
            raise SensitivityPolicyViolation(
                reason=SensitivityFailureReason.MISSING_LEVEL,
            )
        effective = SensitivityPolicy.most_restrictive(
            self.effective_sensitivity,
            *minimums,
        )
        if effective == self.effective_sensitivity:
            return self

        derived = ExecutionContext(
            request_id=self.request_id,
            trace_id=self.trace_id,
            user_id=self.user_id,
            membership_id=self.membership_id,
            firm_id=self.firm_id,
            client_id=self.client_id,
            firm_role=self.firm_role,
            authorization_scope=self.authorization_scope,
            granted_capabilities=self.granted_capabilities,
            effective_sensitivity=effective,
            originating_channel=self.originating_channel,
        )
        derived._issuance_marker = _TRUSTED_EXECUTION_CONTEXT
        LOGGER.info(
            json.dumps(
                {
                    "event": "sensitivity.context_elevated",
                    **self.safe_logging_fields(),
                    "previous_sensitivity": self.effective_sensitivity.value,
                    "effective_sensitivity": effective.value,
                    "policy_result": "ELEVATE",
                },
                sort_keys=True,
            )
        )
        return derived

    def to_firm_context(self) -> FirmContext:
        self._require_trusted()
        return FirmContext(
            user_id=self.user_id,
            membership_id=self.membership_id,
            firm_id=self.firm_id,
            role=self.firm_role,
        )

    def to_client_context(self) -> ClientContext:
        self._require_trusted()
        if self.authorization_scope != AuthorizationScope.CLIENT or self.client_id is None:
            raise AuthorizationDeniedError(
                reason=AuthorizationFailureReason.INVALID_CONTEXT,
            )
        return ClientContext(
            user_id=self.user_id,
            membership_id=self.membership_id,
            firm_id=self.firm_id,
            client_id=self.client_id,
            role=self.firm_role,
        )

    def safe_logging_fields(self) -> dict[str, str | None]:
        """Return the explicit allowlist suitable for structured correlation logs."""

        self._require_trusted()
        return {
            "request_id": str(self.request_id),
            "trace_id": self.trace_id,
            "principal_id": str(self.user_id),
            "membership_id": str(self.membership_id),
            "firm_id": str(self.firm_id),
            "client_id": str(self.client_id) if self.client_id is not None else None,
            "originating_channel": self.originating_channel.value,
        }

    def _require_trusted(self) -> None:
        if self._issuance_marker is not _TRUSTED_EXECUTION_CONTEXT:
            raise AuthorizationDeniedError(
                reason=AuthorizationFailureReason.INVALID_CONTEXT,
            )


def issue_execution_context(
    *,
    authorization: AuthorizationContext,
    request_id: UUID,
    trace_id: TraceId | None,
    effective_sensitivity: SensitivityLevel,
    originating_channel: OriginatingChannel,
) -> ExecutionContext:
    """Issue an authoritative context from an already validated authorization result."""

    if isinstance(authorization, ClientAuthorizationContext):
        tenant_context = authorization.client_context
        client_id = tenant_context.client_id
        scope = AuthorizationScope.CLIENT
    elif isinstance(authorization, FirmAuthorizationContext):
        tenant_context = authorization.firm_context
        client_id = None
        scope = AuthorizationScope.FIRM
    elif isinstance(authorization, SelfAuthorizationContext):
        tenant_context = authorization.firm_context
        client_id = None
        scope = AuthorizationScope.SELF
    else:
        raise AuthorizationDeniedError(
            reason=AuthorizationFailureReason.INVALID_CONTEXT,
        )

    if permission_scope(authorization.granted_permission) != scope:
        raise AuthorizationDeniedError(
            reason=AuthorizationFailureReason.INVALID_CONTEXT,
            permission=authorization.granted_permission,
        )

    context = ExecutionContext(
        request_id=request_id,
        trace_id=trace_id,
        user_id=tenant_context.user_id,
        membership_id=tenant_context.membership_id,
        firm_id=tenant_context.firm_id,
        client_id=client_id,
        firm_role=tenant_context.role,
        authorization_scope=scope,
        granted_capabilities=frozenset({authorization.granted_permission}),
        effective_sensitivity=effective_sensitivity,
        originating_channel=originating_channel,
    )
    context._issuance_marker = _TRUSTED_EXECUTION_CONTEXT
    return context


def require_trusted_execution_context(context: object) -> ExecutionContext:
    """Fail closed unless the value came through Privexa's trusted issuer."""

    if not isinstance(context, ExecutionContext):
        raise AuthorizationDeniedError(
            reason=AuthorizationFailureReason.INVALID_CONTEXT,
        )
    context._require_trusted()
    return context
