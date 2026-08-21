from __future__ import annotations

import pytest
from fixtures.tenant_foundation import (
    ACME_HEALTHCARE_ID,
    ALICE_ID,
    ALICE_MEMBERSHIP_ID,
    APOLLO_FINANCE_ID,
    FIRM_A_ID,
)
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from privexa_api.access_control.context import FirmContext
from privexa_api.access_control.enums import FirmRole
from privexa_api.db.errors import TenantContextConflictError, TenantContextTransactionError
from privexa_api.db.session import validate_runtime_database_security
from privexa_api.db.tenant_scope import (
    TenantContextStage,
    apply_requested_client_scope,
    apply_requested_firm_scope,
    get_tenant_database_context,
)

pytestmark = [pytest.mark.security, pytest.mark.tenant_isolation]


def _firm_context() -> FirmContext:
    return FirmContext(
        user_id=ALICE_ID,
        membership_id=ALICE_MEMBERSHIP_ID,
        firm_id=FIRM_A_ID,
        role=FirmRole.CONSULTANT,
    )


def test_one_session_cannot_switch_clients(tenant_data, app_engine: Engine) -> None:
    with Session(app_engine) as session, session.begin():
        apply_requested_firm_scope(session, _firm_context())
        apply_requested_client_scope(
            session,
            firm_context=_firm_context(),
            client_id=APOLLO_FINANCE_ID,
        )

        with pytest.raises(TenantContextConflictError):
            apply_requested_client_scope(
                session,
                firm_context=_firm_context(),
                client_id=ACME_HEALTHCARE_ID,
            )

        context = get_tenant_database_context(session)
        assert context is not None
        assert context.client_id == APOLLO_FINANCE_ID
        assert context.stage == TenantContextStage.CLIENT_CANDIDATE


def test_tenant_context_cannot_be_established_inside_savepoint(
    tenant_data,
    app_engine: Engine,
) -> None:
    with (
        Session(app_engine) as session,
        session.begin(),
        session.begin_nested(),
        pytest.raises(TenantContextTransactionError),
    ):
        apply_requested_firm_scope(session, _firm_context())


def test_runtime_database_role_passes_security_validation(
    tenant_data,
    app_engine: Engine,
) -> None:
    validate_runtime_database_security(app_engine)
