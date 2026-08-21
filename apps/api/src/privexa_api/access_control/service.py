from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from privexa_api.access_control.context import (
    ClientAuthorizationContext,
    ClientContext,
    FirmAuthorizationContext,
    FirmContext,
    SelfAuthorizationContext,
    _create_client_authorization_context,
    _create_firm_authorization_context,
    _create_self_authorization_context,
)
from privexa_api.access_control.decisions import AuthorizationFailureReason
from privexa_api.access_control.enums import FirmRole, MembershipStatus
from privexa_api.access_control.errors import (
    AuthorizationDeniedError,
    AuthorizationResourceNotFoundError,
)
from privexa_api.access_control.permissions import AuthorizationScope, Permission
from privexa_api.access_control.policy import AuthorizationPolicy
from privexa_api.access_control.repository import AccessControlRepository
from privexa_api.authentication.principal import AuthenticatedPrincipal
from privexa_api.db.tenant_scope import (
    apply_client_scope,
    apply_firm_scope,
    apply_requested_client_scope,
    apply_requested_firm_scope,
)
from privexa_api.identity.enums import FirmStatus, UserStatus

_ALL_FIRM_CLIENT_ROLES = frozenset({FirmRole.FIRM_OWNER, FirmRole.FIRM_ADMIN})
_ASSIGNMENT_REQUIRED_ROLES = frozenset({FirmRole.CONSULTANT, FirmRole.REVIEWER, FirmRole.READ_ONLY})


class AccessControlService:
    @staticmethod
    def _resolve_current_firm_context(
        session: Session,
        *,
        principal: AuthenticatedPrincipal,
        permission: Permission,
    ) -> FirmContext:
        if not isinstance(principal, AuthenticatedPrincipal):
            raise AuthorizationDeniedError(
                reason=AuthorizationFailureReason.INVALID_CONTEXT,
                permission=permission if isinstance(permission, Permission) else None,
            )
        apply_requested_firm_scope(session, principal.firm_context)
        membership = AccessControlRepository.find_membership_for_principal(
            session,
            user_id=principal.user_id,
            membership_id=principal.membership_id,
            firm_id=principal.firm_id,
        )
        if membership is None:
            raise AuthorizationDeniedError(
                reason=AuthorizationFailureReason.FIRM_MEMBERSHIP_REQUIRED,
                permission=permission,
            )
        if (
            membership.user_status != UserStatus.ACTIVE
            or membership.membership_status != MembershipStatus.ACTIVE
            or membership.firm_status != FirmStatus.ACTIVE
        ):
            raise AuthorizationDeniedError(
                reason=AuthorizationFailureReason.FIRM_MEMBERSHIP_INACTIVE,
                permission=permission,
            )
        if membership.role != principal.role:
            raise AuthorizationDeniedError(
                reason=AuthorizationFailureReason.INVALID_CONTEXT,
                permission=permission,
            )
        firm_context = FirmContext(
            user_id=principal.user_id,
            membership_id=principal.membership_id,
            firm_id=principal.firm_id,
            role=membership.role,
        )
        apply_firm_scope(session, firm_context)
        return firm_context

    @staticmethod
    def authorize_firm(
        session: Session,
        *,
        principal: AuthenticatedPrincipal,
        permission: Permission,
    ) -> FirmAuthorizationContext:
        firm_context = AccessControlService._resolve_current_firm_context(
            session,
            principal=principal,
            permission=permission,
        )
        decision = AuthorizationPolicy.evaluate(
            role=firm_context.role,
            permission=permission,
            required_scope=AuthorizationScope.FIRM,
        )
        if not decision.allowed:
            raise AuthorizationDeniedError(
                reason=decision.reason or AuthorizationFailureReason.PERMISSION_DENIED,
                permission=permission,
            )
        return _create_firm_authorization_context(
            firm_context=firm_context,
            permission=permission,
        )

    @staticmethod
    def authorize_client(
        session: Session,
        *,
        principal: AuthenticatedPrincipal,
        client_id: UUID,
        permission: Permission,
    ) -> ClientAuthorizationContext:
        firm_context = AccessControlService._resolve_current_firm_context(
            session,
            principal=principal,
            permission=permission,
        )
        decision = AuthorizationPolicy.evaluate(
            role=firm_context.role,
            permission=permission,
            required_scope=AuthorizationScope.CLIENT,
        )
        if not decision.allowed:
            raise AuthorizationDeniedError(
                reason=decision.reason or AuthorizationFailureReason.PERMISSION_DENIED,
                permission=permission,
            )

        if firm_context.role in _ALL_FIRM_CLIENT_ROLES:
            assignment_required = False
        elif firm_context.role in _ASSIGNMENT_REQUIRED_ROLES:
            assignment_required = True
        else:
            raise AuthorizationDeniedError(
                reason=AuthorizationFailureReason.UNKNOWN_ROLE,
                permission=permission,
            )

        apply_requested_client_scope(session, firm_context=firm_context, client_id=client_id)
        authorized_client_id = AccessControlRepository.find_accessible_active_client(
            session,
            firm_id=firm_context.firm_id,
            membership_id=firm_context.membership_id,
            client_id=client_id,
            assignment_required=assignment_required,
        )
        if authorized_client_id is None:
            raise AuthorizationResourceNotFoundError(
                reason=AuthorizationFailureReason.CLIENT_ACCESS_REQUIRED,
                permission=permission,
            )

        client_context = ClientContext(
            user_id=firm_context.user_id,
            membership_id=firm_context.membership_id,
            firm_id=firm_context.firm_id,
            client_id=authorized_client_id,
            role=firm_context.role,
        )
        apply_client_scope(session, client_context)
        return _create_client_authorization_context(
            client_context=client_context,
            permission=permission,
        )

    @staticmethod
    def authorize_self(
        session: Session,
        *,
        principal: AuthenticatedPrincipal,
        permission: Permission,
    ) -> SelfAuthorizationContext:
        firm_context = AccessControlService._resolve_current_firm_context(
            session,
            principal=principal,
            permission=permission,
        )
        decision = AuthorizationPolicy.evaluate(
            role=firm_context.role,
            permission=permission,
            required_scope=AuthorizationScope.SELF,
        )
        if not decision.allowed:
            raise AuthorizationDeniedError(
                reason=decision.reason or AuthorizationFailureReason.PERMISSION_DENIED,
                permission=permission,
            )
        return _create_self_authorization_context(
            firm_context=firm_context,
            permission=permission,
        )
