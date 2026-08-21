from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from privexa_api.access_control.enums import ClientAccessStatus, FirmRole, MembershipStatus
from privexa_api.access_control.models import ClientAccessGrant
from privexa_api.clients.enums import ClientWorkspaceStatus
from privexa_api.clients.models import ClientWorkspace
from privexa_api.identity.enums import FirmStatus, UserStatus

_RESOLVE_CURRENT_MEMBERSHIP = text(
    """
    SELECT role, user_status, membership_status, firm_status
    FROM privexa_private.resolve_current_membership(:user_id, :membership_id, :firm_id)
    """
)


@dataclass(frozen=True, slots=True)
class CurrentMembershipRecord:
    role: FirmRole
    user_status: UserStatus
    membership_status: MembershipStatus
    firm_status: FirmStatus


class AccessControlRepository:
    @staticmethod
    def find_membership_for_principal(
        session: Session,
        *,
        user_id: UUID,
        membership_id: UUID,
        firm_id: UUID,
    ) -> CurrentMembershipRecord | None:
        row = session.execute(
            _RESOLVE_CURRENT_MEMBERSHIP,
            {
                "user_id": user_id,
                "membership_id": membership_id,
                "firm_id": firm_id,
            },
        ).one_or_none()
        if row is None:
            return None
        return CurrentMembershipRecord(
            role=FirmRole(row.role),
            user_status=UserStatus(row.user_status),
            membership_status=MembershipStatus(row.membership_status),
            firm_status=FirmStatus(row.firm_status),
        )

    @staticmethod
    def find_accessible_active_client(
        session: Session,
        *,
        firm_id: UUID,
        membership_id: UUID,
        client_id: UUID,
        assignment_required: bool,
    ) -> UUID | None:
        statement = select(ClientWorkspace.id).where(
            ClientWorkspace.id == client_id,
            ClientWorkspace.firm_id == firm_id,
            ClientWorkspace.status == ClientWorkspaceStatus.ACTIVE,
        )
        if assignment_required:
            statement = statement.join(
                ClientAccessGrant,
                (ClientAccessGrant.firm_id == ClientWorkspace.firm_id)
                & (ClientAccessGrant.client_id == ClientWorkspace.id)
                & (ClientAccessGrant.membership_id == membership_id),
            ).where(ClientAccessGrant.status == ClientAccessStatus.ACTIVE)
        return session.scalar(statement)
