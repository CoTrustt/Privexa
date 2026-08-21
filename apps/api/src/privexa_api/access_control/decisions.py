from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from privexa_api.access_control.permissions import Permission


class AuthorizationFailureReason(StrEnum):
    INVALID_CONTEXT = "AUTHZ_INVALID_CONTEXT"
    UNKNOWN_ROLE = "AUTHZ_UNKNOWN_ROLE"
    UNKNOWN_PERMISSION = "AUTHZ_UNKNOWN_PERMISSION"
    FIRM_MEMBERSHIP_REQUIRED = "AUTHZ_FIRM_MEMBERSHIP_REQUIRED"
    FIRM_MEMBERSHIP_INACTIVE = "AUTHZ_FIRM_MEMBERSHIP_INACTIVE"
    CLIENT_ACCESS_REQUIRED = "AUTHZ_CLIENT_ACCESS_REQUIRED"
    PERMISSION_DENIED = "AUTHZ_PERMISSION_DENIED"
    RESOURCE_SCOPE_MISMATCH = "AUTHZ_RESOURCE_SCOPE_MISMATCH"


@dataclass(frozen=True, slots=True)
class AuthorizationDecision:
    allowed: bool
    permission: Permission | None
    reason: AuthorizationFailureReason | None

    @classmethod
    def allow(cls, permission: Permission) -> AuthorizationDecision:
        return cls(allowed=True, permission=permission, reason=None)

    @classmethod
    def deny(
        cls,
        *,
        permission: Permission | None,
        reason: AuthorizationFailureReason,
    ) -> AuthorizationDecision:
        return cls(allowed=False, permission=permission, reason=reason)
