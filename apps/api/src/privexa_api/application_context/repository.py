from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from privexa_api.application_context.models import ActiveClientSession

_LIST_AUTHORIZED_ACTIVE_CLIENTS = text(
    """
    SELECT client_id, display_name
    FROM privexa_private.list_authorized_active_clients()
    ORDER BY lower(display_name), client_id
    """
)


@dataclass(frozen=True, slots=True)
class AuthorizedClientRecord:
    client_id: UUID
    display_name: str


class ApplicationContextRepository:
    @staticmethod
    def list_authorized_active_clients(session: Session) -> list[AuthorizedClientRecord]:
        return [
            AuthorizedClientRecord(client_id=row.client_id, display_name=row.display_name)
            for row in session.execute(_LIST_AUTHORIZED_ACTIVE_CLIENTS)
        ]

    @staticmethod
    def find_active_client_id(
        session: Session,
        *,
        firm_id: UUID,
        membership_id: UUID,
        session_fingerprint: str,
    ) -> UUID | None:
        return session.scalar(
            select(ActiveClientSession.active_client_id).where(
                ActiveClientSession.firm_id == firm_id,
                ActiveClientSession.membership_id == membership_id,
                ActiveClientSession.session_fingerprint == session_fingerprint,
            )
        )

    @staticmethod
    def set_active_client(
        session: Session,
        *,
        firm_id: UUID,
        membership_id: UUID,
        client_id: UUID,
        session_fingerprint: str,
    ) -> UUID | None:
        previous_client_id = ApplicationContextRepository.find_active_client_id(
            session,
            firm_id=firm_id,
            membership_id=membership_id,
            session_fingerprint=session_fingerprint,
        )
        statement = insert(ActiveClientSession).values(
            id=uuid4(),
            firm_id=firm_id,
            membership_id=membership_id,
            active_client_id=client_id,
            session_fingerprint=session_fingerprint,
        )
        statement = statement.on_conflict_do_update(
            constraint="uq_active_client_sessions_firm_membership_session",
            set_={"active_client_id": client_id, "updated_at": text("CURRENT_TIMESTAMP")},
        )
        session.execute(statement)
        return previous_client_id
