from __future__ import annotations

from privexa_api.access_control.decisions import AuthorizationFailureReason
from privexa_api.access_control.permissions import Permission


class AuthorizationProblem(Exception):
    """Base authorization failure carrying private diagnostic information."""

    def __init__(
        self,
        *,
        reason: AuthorizationFailureReason,
        permission: Permission | None = None,
    ) -> None:
        super().__init__(reason.value)
        self.reason = reason
        self.permission = permission


class AuthorizationDeniedError(AuthorizationProblem):
    """The principal has a visible scope but lacks authority for the action."""


class AuthorizationResourceNotFoundError(AuthorizationProblem):
    """The requested scope is unavailable without revealing whether it exists."""
