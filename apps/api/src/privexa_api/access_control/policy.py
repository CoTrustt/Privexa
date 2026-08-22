from __future__ import annotations

from types import MappingProxyType

from privexa_api.access_control.context import (
    AuthorizationContext,
    ClientAuthorizationContext,
    FirmAuthorizationContext,
    SelfAuthorizationContext,
)
from privexa_api.access_control.decisions import (
    AuthorizationDecision,
    AuthorizationFailureReason,
)
from privexa_api.access_control.enums import FirmRole
from privexa_api.access_control.errors import AuthorizationDeniedError
from privexa_api.access_control.permissions import (
    AuthorizationScope,
    Permission,
    permission_scope,
)

_OWNER_PERMISSIONS = frozenset(Permission)
_ADMIN_PERMISSIONS = _OWNER_PERMISSIONS - {Permission.FIRM_OWNERS_MANAGE}
_BASE_ASSIGNED_CLIENT_PERMISSIONS = frozenset(
    {
        Permission.FIRM_READ,
        Permission.CLIENT_READ,
        Permission.QUESTION_READ,
        Permission.PROFILE_READ_SELF,
        Permission.PROFILE_UPDATE_SELF,
    }
)
_CONSULTANT_PERMISSIONS = _BASE_ASSIGNED_CLIENT_PERMISSIONS | {
    Permission.FILE_CREATE,
    Permission.FILE_READ,
    Permission.FILE_DELETE,
    Permission.QUESTION_CREATE,
    Permission.QUESTION_UPDATE,
}
_REVIEWER_PERMISSIONS = _BASE_ASSIGNED_CLIENT_PERMISSIONS | {Permission.FILE_READ}
_READ_ONLY_PERMISSIONS = _BASE_ASSIGNED_CLIENT_PERMISSIONS | {Permission.FILE_READ}

ROLE_PERMISSIONS = MappingProxyType(
    {
        FirmRole.FIRM_OWNER: _OWNER_PERMISSIONS,
        FirmRole.FIRM_ADMIN: _ADMIN_PERMISSIONS,
        FirmRole.CONSULTANT: _CONSULTANT_PERMISSIONS,
        FirmRole.REVIEWER: _REVIEWER_PERMISSIONS,
        FirmRole.READ_ONLY: _READ_ONLY_PERMISSIONS,
    }
)


class AuthorizationPolicy:
    @staticmethod
    def evaluate(
        *,
        role: FirmRole,
        permission: Permission,
        required_scope: AuthorizationScope,
    ) -> AuthorizationDecision:
        if not isinstance(permission, Permission) or permission_scope(permission) is None:
            return AuthorizationDecision.deny(
                permission=None,
                reason=AuthorizationFailureReason.UNKNOWN_PERMISSION,
            )
        if permission_scope(permission) != required_scope:
            return AuthorizationDecision.deny(
                permission=permission,
                reason=AuthorizationFailureReason.INVALID_CONTEXT,
            )

        role_permissions = ROLE_PERMISSIONS.get(role)
        if role_permissions is None:
            return AuthorizationDecision.deny(
                permission=permission,
                reason=AuthorizationFailureReason.UNKNOWN_ROLE,
            )
        if permission not in role_permissions:
            return AuthorizationDecision.deny(
                permission=permission,
                reason=AuthorizationFailureReason.PERMISSION_DENIED,
            )
        return AuthorizationDecision.allow(permission)

    @staticmethod
    def require(
        context: AuthorizationContext,
        permission: Permission,
    ) -> None:
        if not isinstance(
            context,
            (FirmAuthorizationContext, ClientAuthorizationContext, SelfAuthorizationContext),
        ) or not isinstance(permission, Permission):
            raise AuthorizationDeniedError(
                reason=AuthorizationFailureReason.INVALID_CONTEXT,
                permission=permission if isinstance(permission, Permission) else None,
            )
        if context.granted_permission != permission:
            raise AuthorizationDeniedError(
                reason=AuthorizationFailureReason.INVALID_CONTEXT,
                permission=permission,
            )
