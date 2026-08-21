from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from privexa_api.access_control.context import ClientContext
from privexa_api.clients.enums import ClientWorkspaceStatus
from privexa_api.clients.models import ClientWorkspace


class ClientWorkspaceRepository:
    """Tenant-scoped persistence only; application authorization belongs in services."""

    @staticmethod
    def get_active(
        session: Session,
        *,
        context: ClientContext,
    ) -> ClientWorkspace | None:
        statement = select(ClientWorkspace).where(
            ClientWorkspace.id == context.client_id,
            ClientWorkspace.firm_id == context.firm_id,
            ClientWorkspace.status == ClientWorkspaceStatus.ACTIVE,
        )
        return session.scalar(statement)
