from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from privexa_api.access_control.context import ClientContext, FirmContext
from privexa_api.db.errors import TenantContextConflictError, TenantContextTransactionError

_SET_LOCAL_CONTEXT = text("SELECT set_config(:setting_name, :setting_value, true)")
_SESSION_CONTEXT_KEY = "privexa.database_security_context"


class TenantContextStage(StrEnum):
    FIRM_CANDIDATE = "FIRM_CANDIDATE"
    FIRM = "FIRM"
    CLIENT_CANDIDATE = "CLIENT_CANDIDATE"
    CLIENT = "CLIENT"


@dataclass(frozen=True, slots=True)
class TenantDatabaseContext:
    """Typed tenant identity bound to one SQLAlchemy Session.

    Candidate stages contain authenticated identifiers that PostgreSQL must still validate against
    authoritative membership and assignment data. Final stages are produced only after that
    protected lookup succeeds.
    """

    user_id: UUID
    membership_id: UUID
    firm_id: UUID
    client_id: UUID | None
    stage: TenantContextStage


def get_tenant_database_context(session: Session) -> TenantDatabaseContext | None:
    context = session.info.get(_SESSION_CONTEXT_KEY)
    return context if isinstance(context, TenantDatabaseContext) else None


def _assert_transaction_is_safe(session: Session, context: TenantDatabaseContext) -> None:
    if session.in_nested_transaction():
        # SET LOCAL changes can be reverted with a savepoint while Session.info cannot. Keeping
        # tenant establishment at the outer transaction avoids those states diverging.
        raise TenantContextTransactionError(
            firm_id=context.firm_id,
            client_id=context.client_id,
        )


def _assert_compatible_context(
    existing: TenantDatabaseContext | None,
    requested: TenantDatabaseContext,
) -> None:
    if existing is None:
        return
    if (
        existing.user_id != requested.user_id
        or existing.membership_id != requested.membership_id
        or existing.firm_id != requested.firm_id
        or (
            existing.client_id is not None
            and requested.client_id is not None
            and existing.client_id != requested.client_id
        )
    ):
        # A Session identity map can return an already-loaded object without issuing SQL.
        # Never allow a Session to change tenant even though its connection is transaction-local.
        raise TenantContextConflictError(
            firm_id=requested.firm_id,
            client_id=requested.client_id,
        )


def _merge_context(
    existing: TenantDatabaseContext | None,
    requested: TenantDatabaseContext,
) -> TenantDatabaseContext:
    if existing is None:
        return requested
    if existing.client_id is not None and requested.client_id is None:
        return existing
    stage_order = {
        TenantContextStage.FIRM_CANDIDATE: 0,
        TenantContextStage.FIRM: 1,
        TenantContextStage.CLIENT_CANDIDATE: 2,
        TenantContextStage.CLIENT: 3,
    }
    if (
        existing.client_id == requested.client_id
        and stage_order[existing.stage] >= stage_order[requested.stage]
    ):
        return existing
    return requested


def _apply_scope_settings(
    session: Session,
    *,
    context: TenantDatabaseContext,
) -> None:
    settings = {
        "privexa.user_id": context.user_id,
        "privexa.membership_id": context.membership_id,
        "privexa.firm_id": context.firm_id,
        "privexa.client_id": context.client_id or "",
    }
    for setting_name, setting_value in settings.items():
        session.execute(
            _SET_LOCAL_CONTEXT,
            {"setting_name": setting_name, "setting_value": str(setting_value)},
        )


def _apply_context(session: Session, requested: TenantDatabaseContext) -> None:
    _assert_transaction_is_safe(session, requested)
    existing = get_tenant_database_context(session)
    _assert_compatible_context(existing, requested)
    effective = _merge_context(existing, requested)
    _apply_scope_settings(session, context=effective)
    session.info[_SESSION_CONTEXT_KEY] = effective


def apply_requested_firm_scope(session: Session, context: FirmContext) -> None:
    """Apply candidate authenticated Firm identifiers for database revalidation."""

    _apply_context(
        session,
        TenantDatabaseContext(
            user_id=context.user_id,
            membership_id=context.membership_id,
            firm_id=context.firm_id,
            client_id=None,
            stage=TenantContextStage.FIRM_CANDIDATE,
        ),
    )


def apply_firm_scope(session: Session, context: FirmContext) -> None:
    """Apply Firm scope after authentication or current-state authorization succeeds."""

    existing = get_tenant_database_context(session)
    if existing is not None and existing.client_id is not None:
        requested = existing
    else:
        requested = TenantDatabaseContext(
            user_id=context.user_id,
            membership_id=context.membership_id,
            firm_id=context.firm_id,
            client_id=None,
            stage=TenantContextStage.FIRM,
        )
    _apply_context(session, requested)


def apply_requested_client_scope(
    session: Session,
    *,
    firm_context: FirmContext,
    client_id: UUID,
) -> None:
    """Set candidate client scope so RLS can validate client access.

    `firm_context` is already authorized. `client_id` remains untrusted until a query protected by
    the client RLS policies succeeds.
    """
    _apply_context(
        session,
        TenantDatabaseContext(
            user_id=firm_context.user_id,
            membership_id=firm_context.membership_id,
            firm_id=firm_context.firm_id,
            client_id=client_id,
            stage=TenantContextStage.CLIENT_CANDIDATE,
        ),
    )


def apply_client_scope(session: Session, context: ClientContext) -> None:
    """Apply fully validated context to the current transaction for PostgreSQL RLS."""
    _apply_context(
        session,
        TenantDatabaseContext(
            user_id=context.user_id,
            membership_id=context.membership_id,
            firm_id=context.firm_id,
            client_id=context.client_id,
            stage=TenantContextStage.CLIENT,
        ),
    )
