from __future__ import annotations

from uuid import uuid4

import pytest
from fixtures.tenant_foundation import (
    FIRM_A_ID,
    STYTCH_ALICE_ID,
    STYTCH_FIRM_A_ID,
)
from pydantic import SecretStr, ValidationError
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from privexa_api.access_control.enums import FirmRole
from privexa_api.access_control.models import ClientAccessGrant, FirmMembership
from privexa_api.clients.models import ClientWorkspace
from privexa_api.config import Settings
from privexa_api.development.provision import validate_development_target
from privexa_api.development.provisioning import (
    DevelopmentIdentitySpec,
    DevelopmentProvisioningError,
    provision_development_identity,
)
from privexa_api.identity.models import Firm, User


def _settings(*, environment: str, database_name: str) -> Settings:
    return Settings(
        APP_DATABASE_URL=f"postgresql+psycopg://runtime@localhost/{database_name}",
        STYTCH_PROJECT_ID="project-test-privexa",
        STYTCH_SECRET=SecretStr("secret-test-privexa"),
        PRIVEXA_ENVIRONMENT=environment,
    )


def test_development_runtime_refuses_test_database() -> None:
    with pytest.raises(ValidationError, match="must not target a database ending in '_test'"):
        _settings(environment="development", database_name="privexa_test")


def test_database_environment_pairings_accept_isolated_targets() -> None:
    development = _settings(environment="development", database_name="privexa_dev")
    test = _settings(environment="test", database_name="privexa_test")

    assert development.app_database_url.endswith("/privexa_dev")
    assert test.app_database_url.endswith("/privexa_test")


@pytest.mark.parametrize(
    ("environment", "database_name"),
    [
        ("test", "privexa_dev"),
        ("development", "privexa_test"),
    ],
)
def test_local_provisioning_refuses_unsafe_target(
    environment: str,
    database_name: str,
) -> None:
    with pytest.raises(DevelopmentProvisioningError):
        validate_development_target(
            environment=environment,
            database_url=f"postgresql+psycopg://owner@localhost/{database_name}",
        )


def test_local_provisioning_accepts_development_database() -> None:
    validate_development_target(
        environment="development",
        database_url="postgresql+psycopg://owner@localhost/privexa_dev",
    )


def test_provisioning_is_idempotent_and_assigns_only_requested_client(
    tenant_data,
    owner_engine: Engine,
) -> None:
    suffix = uuid4()
    spec = DevelopmentIdentitySpec(
        firm_name="Development Provisioning Firm",
        stytch_organization_id=f"organization-test-{suffix}",
        email="manual.consultant@example.test",
        display_name="Manual Consultant",
        role=FirmRole.CONSULTANT,
        stytch_member_id=f"member-test-{suffix}",
        client_names=("Unassigned Sandbox",),
        assigned_client_names=("Assigned Sandbox",),
    )

    with Session(owner_engine) as session, session.begin():
        first = provision_development_identity(session, spec=spec)
    with Session(owner_engine) as session, session.begin():
        second = provision_development_identity(session, spec=spec)

    assert first == second
    assert set(first.client_ids) == {"Assigned Sandbox", "Unassigned Sandbox"}
    assert set(first.assigned_client_ids) == {"Assigned Sandbox"}

    with Session(owner_engine) as session:
        assert (
            session.scalar(select(func.count()).select_from(Firm).where(Firm.id == first.firm_id))
            == 1
        )
        assert (
            session.scalar(select(func.count()).select_from(User).where(User.id == first.user_id))
            == 1
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(FirmMembership)
                .where(FirmMembership.id == first.membership_id)
            )
            == 1
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(ClientWorkspace)
                .where(ClientWorkspace.firm_id == first.firm_id)
            )
            == 2
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(ClientAccessGrant)
                .where(ClientAccessGrant.membership_id == first.membership_id)
            )
            == 1
        )


def test_owner_provisioning_rejects_redundant_client_assignment(
    tenant_data,
    owner_engine: Engine,
) -> None:
    with (
        Session(owner_engine) as session,
        pytest.raises(DevelopmentProvisioningError, match="access all same-firm clients"),
    ):
        provision_development_identity(
            session,
            spec=DevelopmentIdentitySpec(
                firm_name="Owner Firm",
                stytch_organization_id=f"organization-test-{uuid4()}",
                email="owner@example.test",
                display_name="Owner",
                role=FirmRole.FIRM_OWNER,
                stytch_member_id=f"member-test-{uuid4()}",
                assigned_client_names=("Redundant Assignment",),
            ),
        )


def test_provisioning_rejects_stytch_member_bound_to_another_membership(
    tenant_data,
    owner_engine: Engine,
) -> None:
    with (
        Session(owner_engine) as session,
        pytest.raises(DevelopmentProvisioningError, match="already bound"),
    ):
        provision_development_identity(
            session,
            spec=DevelopmentIdentitySpec(
                firm_name=tenant_data.firm_a.name,
                stytch_organization_id=STYTCH_FIRM_A_ID,
                email="another.user@example.test",
                display_name="Another User",
                role=FirmRole.CONSULTANT,
                stytch_member_id=STYTCH_ALICE_ID,
            ),
        )


def test_provisioning_does_not_cross_existing_firm_binding(
    tenant_data,
    owner_engine: Engine,
) -> None:
    with (
        Session(owner_engine) as session,
        pytest.raises(DevelopmentProvisioningError, match="another Stytch organization"),
    ):
        provision_development_identity(
            session,
            spec=DevelopmentIdentitySpec(
                firm_name=tenant_data.firm_a.name,
                stytch_organization_id=f"organization-test-{uuid4()}",
                email="owner2@example.test",
                display_name="Owner Two",
                role=FirmRole.FIRM_OWNER,
                stytch_member_id=f"member-test-{uuid4()}",
            ),
        )

    assert tenant_data.firm_a.id == FIRM_A_ID
