from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from privexa_api.access_control.context import FirmContext
from privexa_api.access_control.enums import MembershipStatus
from privexa_api.authentication.errors import (
    FirmInactiveError,
    MemberNotProvisionedError,
    MembershipInactiveError,
)
from privexa_api.authentication.principal import AuthenticatedPrincipal
from privexa_api.authentication.stytch_gateway import ValidatedStytchSession
from privexa_api.db.tenant_scope import apply_firm_scope
from privexa_api.identity.enums import FirmStatus, UserStatus
from privexa_api.identity.repository import IdentityRepository


@dataclass(frozen=True, slots=True)
class AuthenticatedIdentity:
    principal: AuthenticatedPrincipal
    firm_name: str
    display_name: str


class AuthenticationService:
    @staticmethod
    def resolve_identity(
        session: Session,
        *,
        validated_session: ValidatedStytchSession,
    ) -> AuthenticatedIdentity:
        membership = IdentityRepository.find_external_membership(
            session,
            stytch_member_id=validated_session.member_id,
            stytch_organization_id=validated_session.organization_id,
        )
        if membership is None:
            raise MemberNotProvisionedError
        if membership.firm_status != FirmStatus.ACTIVE:
            raise FirmInactiveError
        if (
            membership.user_status != UserStatus.ACTIVE
            or membership.membership_status != MembershipStatus.ACTIVE
        ):
            raise MembershipInactiveError

        firm_context = FirmContext(
            user_id=membership.user_id,
            membership_id=membership.membership_id,
            firm_id=membership.firm_id,
            role=membership.role,
        )
        apply_firm_scope(session, firm_context)
        return AuthenticatedIdentity(
            principal=AuthenticatedPrincipal(
                firm_context=firm_context,
                stytch_member_id=validated_session.member_id,
                stytch_organization_id=validated_session.organization_id,
                stytch_member_session_id=validated_session.member_session_id,
            ),
            firm_name=membership.firm_name,
            display_name=membership.display_name,
        )
