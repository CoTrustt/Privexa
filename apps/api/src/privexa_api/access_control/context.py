from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from privexa_api.access_control.enums import FirmRole
from privexa_api.access_control.permissions import Permission

_VALIDATED_AUTHORIZATION_CONTEXT = object()


@dataclass(frozen=True, slots=True)
class FirmContext:
    user_id: UUID
    membership_id: UUID
    firm_id: UUID
    role: FirmRole


@dataclass(frozen=True, slots=True)
class ClientContext:
    """Application-authorized tenant context for one client workspace."""

    user_id: UUID
    membership_id: UUID
    firm_id: UUID
    client_id: UUID
    role: FirmRole


@dataclass(frozen=True, slots=True, init=False)
class FirmAuthorizationContext:
    """A firm scope for exactly one permission validated by AccessControlService."""

    firm_context: FirmContext
    granted_permission: Permission

    def __init__(
        self,
        *,
        _validation_token: object,
        firm_context: FirmContext,
        granted_permission: Permission,
    ) -> None:
        if _validation_token is not _VALIDATED_AUTHORIZATION_CONTEXT:
            raise TypeError("Authorization contexts must be created by AccessControlService")
        object.__setattr__(self, "firm_context", firm_context)
        object.__setattr__(self, "granted_permission", granted_permission)


@dataclass(frozen=True, slots=True, init=False)
class SelfAuthorizationContext:
    """Authority for the principal's own safe profile operations."""

    firm_context: FirmContext
    granted_permission: Permission

    def __init__(
        self,
        *,
        _validation_token: object,
        firm_context: FirmContext,
        granted_permission: Permission,
    ) -> None:
        if _validation_token is not _VALIDATED_AUTHORIZATION_CONTEXT:
            raise TypeError("Authorization contexts must be created by AccessControlService")
        object.__setattr__(self, "firm_context", firm_context)
        object.__setattr__(self, "granted_permission", granted_permission)


@dataclass(frozen=True, slots=True, init=False)
class ClientAuthorizationContext:
    """A client scope for exactly one permission validated by AccessControlService."""

    client_context: ClientContext
    granted_permission: Permission

    def __init__(
        self,
        *,
        _validation_token: object,
        client_context: ClientContext,
        granted_permission: Permission,
    ) -> None:
        if _validation_token is not _VALIDATED_AUTHORIZATION_CONTEXT:
            raise TypeError("Authorization contexts must be created by AccessControlService")
        object.__setattr__(self, "client_context", client_context)
        object.__setattr__(self, "granted_permission", granted_permission)


def _create_firm_authorization_context(
    *,
    firm_context: FirmContext,
    permission: Permission,
) -> FirmAuthorizationContext:
    return FirmAuthorizationContext(
        _validation_token=_VALIDATED_AUTHORIZATION_CONTEXT,
        firm_context=firm_context,
        granted_permission=permission,
    )


def _create_client_authorization_context(
    *,
    client_context: ClientContext,
    permission: Permission,
) -> ClientAuthorizationContext:
    return ClientAuthorizationContext(
        _validation_token=_VALIDATED_AUTHORIZATION_CONTEXT,
        client_context=client_context,
        granted_permission=permission,
    )


def _create_self_authorization_context(
    *,
    firm_context: FirmContext,
    permission: Permission,
) -> SelfAuthorizationContext:
    return SelfAuthorizationContext(
        _validation_token=_VALIDATED_AUTHORIZATION_CONTEXT,
        firm_context=firm_context,
        granted_permission=permission,
    )


AuthorizationContext = (
    FirmAuthorizationContext | ClientAuthorizationContext | SelfAuthorizationContext
)
