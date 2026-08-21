from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from privexa_api.access_control.enums import FirmRole, MembershipStatus
from privexa_api.identity.enums import FirmStatus, UserStatus

_RESOLVE_AUTHENTICATED_IDENTITY = text(
    """
    SELECT
        user_id,
        membership_id,
        firm_id,
        role,
        user_status,
        membership_status,
        firm_status,
        firm_name,
        display_name
    FROM privexa_private.resolve_authenticated_identity(
        :stytch_member_id,
        :stytch_organization_id
    )
    """
)


@dataclass(frozen=True, slots=True)
class ExternalMembershipRecord:
    user_id: UUID
    membership_id: UUID
    firm_id: UUID
    role: FirmRole
    user_status: UserStatus
    membership_status: MembershipStatus
    firm_status: FirmStatus
    firm_name: str
    display_name: str


class IdentityRepository:
    @staticmethod
    def find_external_membership(
        session: Session,
        *,
        stytch_member_id: str,
        stytch_organization_id: str,
    ) -> ExternalMembershipRecord | None:
        # Authentication resolves an exact provider identity before normal RLS context exists.
        # The database function exposes only this bounded lookup, not a general bypass session.
        row = session.execute(
            _RESOLVE_AUTHENTICATED_IDENTITY,
            {
                "stytch_member_id": stytch_member_id,
                "stytch_organization_id": stytch_organization_id,
            },
        ).one_or_none()
        if row is None:
            return None

        return ExternalMembershipRecord(
            user_id=row.user_id,
            membership_id=row.membership_id,
            firm_id=row.firm_id,
            role=FirmRole(row.role),
            user_status=UserStatus(row.user_status),
            membership_status=MembershipStatus(row.membership_status),
            firm_status=FirmStatus(row.firm_status),
            firm_name=row.firm_name,
            display_name=row.display_name,
        )
