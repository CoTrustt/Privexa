from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fixtures.tenant_foundation import (
    ALICE_ID,
    ALICE_MEMBERSHIP_ID,
    FIRM_A_ID,
    STYTCH_ALICE_ID,
    STYTCH_FIRM_A_ID,
)
from sqlalchemy import Engine, update
from sqlalchemy.orm import Session

from privexa_api.access_control.enums import FirmRole, MembershipStatus
from privexa_api.access_control.models import FirmMembership
from privexa_api.authentication.errors import (
    FirmInactiveError,
    MemberNotProvisionedError,
    MembershipInactiveError,
)
from privexa_api.authentication.service import AuthenticationService
from privexa_api.authentication.stytch_gateway import ValidatedStytchSession
from privexa_api.identity.enums import FirmStatus, UserStatus
from privexa_api.identity.models import Firm, User


def _validated_session(
    *,
    member_id: str = STYTCH_ALICE_ID,
    organization_id: str = STYTCH_FIRM_A_ID,
) -> ValidatedStytchSession:
    return ValidatedStytchSession(
        member_id=member_id,
        organization_id=organization_id,
        member_session_id="member-session-test-alice",
        request_id="request-test-alice",
    )


def test_resolves_active_stytch_identity_to_existing_firm_context(
    tenant_data,
    app_engine: Engine,
) -> None:
    with Session(app_engine) as session:
        identity = AuthenticationService.resolve_identity(
            session,
            validated_session=_validated_session(),
        )

    assert identity.principal.user_id == ALICE_ID
    assert identity.principal.membership_id == ALICE_MEMBERSHIP_ID
    assert identity.principal.firm_id == FIRM_A_ID
    assert identity.principal.role == FirmRole.CONSULTANT
    assert identity.principal.stytch_member_id == STYTCH_ALICE_ID
    assert identity.firm_name == "Pai Privacy Consulting"


def test_requires_matching_member_and_organization_pair(tenant_data, app_engine: Engine) -> None:
    with Session(app_engine) as session, pytest.raises(MemberNotProvisionedError):
        AuthenticationService.resolve_identity(
            session,
            validated_session=_validated_session(organization_id="organization-test-firm-b"),
        )


def test_unknown_stytch_identity_is_not_provisioned(tenant_data, app_engine: Engine) -> None:
    with Session(app_engine) as session, pytest.raises(MemberNotProvisionedError):
        AuthenticationService.resolve_identity(
            session,
            validated_session=_validated_session(member_id="member-test-unknown"),
        )


@pytest.mark.parametrize("disabled_record", ["user", "membership"])
def test_inactive_human_or_membership_is_denied(
    tenant_data,
    owner_engine: Engine,
    app_engine: Engine,
    disabled_record: str,
) -> None:
    with Session(owner_engine) as session, session.begin():
        if disabled_record == "user":
            session.execute(
                update(User).where(User.id == ALICE_ID).values(status=UserStatus.DISABLED)
            )
        else:
            session.execute(
                update(FirmMembership)
                .where(FirmMembership.id == ALICE_MEMBERSHIP_ID)
                .values(status=MembershipStatus.REVOKED, revoked_at=datetime.now(UTC))
            )

    with Session(app_engine) as session, pytest.raises(MembershipInactiveError):
        AuthenticationService.resolve_identity(
            session,
            validated_session=_validated_session(),
        )


def test_inactive_firm_is_denied(
    tenant_data,
    owner_engine: Engine,
    app_engine: Engine,
) -> None:
    with Session(owner_engine) as session, session.begin():
        session.execute(
            update(Firm).where(Firm.id == FIRM_A_ID).values(status=FirmStatus.SUSPENDED)
        )

    with Session(app_engine) as session, pytest.raises(FirmInactiveError):
        AuthenticationService.resolve_identity(
            session,
            validated_session=_validated_session(),
        )
