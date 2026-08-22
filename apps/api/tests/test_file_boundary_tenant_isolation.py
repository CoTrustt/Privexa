from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from fixtures.tenant_foundation import (
    ACME_HEALTHCARE_ID,
    ALICE_ID,
    ALICE_MEMBERSHIP_ID,
    APOLLO_FINANCE_ID,
    BOB_ID,
    BOB_MEMBERSHIP_ID,
    DAVID_MEMBERSHIP_ID,
    FIRM_A_ID,
    FIRM_B_ID,
    MERIDIAN_RETAIL_ID,
    NORTHSTAR_RETAIL_ID,
)
from sqlalchemy import Engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from privexa_api.access_control.context import FirmContext
from privexa_api.access_control.enums import FirmRole
from privexa_api.access_control.permissions import Permission
from privexa_api.access_control.service import AccessControlService
from privexa_api.authentication.principal import AuthenticatedPrincipal
from privexa_api.files.enums import StorageProvider, StoredFileStatus
from privexa_api.files.models import StoredFile
from privexa_api.security.enums import SensitivityLevel
from privexa_api.storage.keys import build_stored_file_keys

pytestmark = [pytest.mark.security, pytest.mark.tenant_isolation]


def _principal(
    *, user_id: UUID, membership_id: UUID, firm_id: UUID, role: FirmRole
) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        firm_context=FirmContext(
            user_id=user_id,
            membership_id=membership_id,
            firm_id=firm_id,
            role=role,
        ),
        stytch_member_id=f"member-{user_id}",
        stytch_organization_id=f"organization-{firm_id}",
        stytch_member_session_id=f"session-{membership_id}",
    )


def _stored_file(
    *,
    file_id: UUID,
    firm_id: UUID,
    client_id: UUID,
    membership_id: UUID,
) -> StoredFile:
    keys = build_stored_file_keys(firm_id=firm_id, client_id=client_id, file_id=file_id)
    return StoredFile(
        id=file_id,
        firm_id=firm_id,
        client_id=client_id,
        storage_provider=StorageProvider.S3_COMPATIBLE,
        storage_bucket="privexa-test",
        storage_key=keys.storage_key,
        upload_storage_key=keys.upload_key,
        original_filename="fixture.pdf",
        mime_type="application/pdf",
        size_bytes=10,
        checksum_sha256="a" * 64,
        status=StoredFileStatus.PENDING_UPLOAD,
        sensitivity_level=SensitivityLevel.SENSITIVE,
        created_by_membership_id=membership_id,
        upload_expires_at=datetime.now(UTC) + timedelta(minutes=15),
    )


def test_actual_rls_hides_same_firm_other_client_and_cross_firm_files(
    tenant_data,
    owner_engine: Engine,
    app_engine: Engine,
) -> None:
    apollo_id = UUID("00000000-0000-4000-8000-000000000801")
    meridian_id = UUID("00000000-0000-4000-8000-000000000802")
    northstar_id = UUID("00000000-0000-4000-8000-000000000803")
    with Session(owner_engine) as session, session.begin():
        session.add_all(
            [
                _stored_file(
                    file_id=apollo_id,
                    firm_id=FIRM_A_ID,
                    client_id=APOLLO_FINANCE_ID,
                    membership_id=ALICE_MEMBERSHIP_ID,
                ),
                _stored_file(
                    file_id=meridian_id,
                    firm_id=FIRM_A_ID,
                    client_id=MERIDIAN_RETAIL_ID,
                    membership_id=DAVID_MEMBERSHIP_ID,
                ),
                _stored_file(
                    file_id=northstar_id,
                    firm_id=FIRM_B_ID,
                    client_id=NORTHSTAR_RETAIL_ID,
                    membership_id=BOB_MEMBERSHIP_ID,
                ),
            ]
        )

    with Session(app_engine) as session, session.begin():
        AccessControlService.authorize_client(
            session,
            principal=_principal(
                user_id=ALICE_ID,
                membership_id=ALICE_MEMBERSHIP_ID,
                firm_id=FIRM_A_ID,
                role=FirmRole.CONSULTANT,
            ),
            client_id=APOLLO_FINANCE_ID,
            permission=Permission.FILE_READ,
        )
        visible_ids = set(session.scalars(select(StoredFile.id)))
        same_firm = session.get(StoredFile, meridian_id)
        cross_firm = session.get(StoredFile, northstar_id)

    assert visible_ids == {apollo_id}
    assert same_firm is None
    assert cross_firm is None


def test_composite_foreign_key_rejects_cross_firm_client_relationship(
    tenant_data,
    owner_engine: Engine,
) -> None:
    with pytest.raises(IntegrityError), Session(owner_engine) as session, session.begin():
        session.add(
            _stored_file(
                file_id=UUID("00000000-0000-4000-8000-000000000804"),
                firm_id=FIRM_A_ID,
                client_id=NORTHSTAR_RETAIL_ID,
                membership_id=ALICE_MEMBERSHIP_ID,
            )
        )
        session.flush()


@pytest.mark.parametrize(
    ("firm_id", "client_id"),
    [
        (UUID("00000000-0000-4000-8000-999999999901"), APOLLO_FINANCE_ID),
        (FIRM_A_ID, UUID("00000000-0000-4000-8000-999999999902")),
        (None, APOLLO_FINANCE_ID),
        (FIRM_A_ID, None),
    ],
)
def test_database_rejects_missing_nonexistent_or_null_file_ownership(
    tenant_data,
    owner_engine: Engine,
    firm_id: UUID | None,
    client_id: UUID | None,
) -> None:
    stored_file = _stored_file(
        file_id=UUID("00000000-0000-4000-8000-999999999903"),
        firm_id=FIRM_A_ID,
        client_id=APOLLO_FINANCE_ID,
        membership_id=ALICE_MEMBERSHIP_ID,
    )
    stored_file.firm_id = firm_id  # type: ignore[assignment]
    stored_file.client_id = client_id  # type: ignore[assignment]
    with pytest.raises(IntegrityError), Session(owner_engine) as session, session.begin():
        session.add(stored_file)
        session.flush()


def test_missing_context_and_alternating_pooled_connections_never_leak_files(
    tenant_data,
    owner_engine: Engine,
    app_engine: Engine,
) -> None:
    apollo_id = UUID("00000000-0000-4000-8000-000000000811")
    acme_id = UUID("00000000-0000-4000-8000-000000000812")
    northstar_id = UUID("00000000-0000-4000-8000-000000000813")
    with Session(owner_engine) as session, session.begin():
        session.add_all(
            [
                _stored_file(
                    file_id=apollo_id,
                    firm_id=FIRM_A_ID,
                    client_id=APOLLO_FINANCE_ID,
                    membership_id=ALICE_MEMBERSHIP_ID,
                ),
                _stored_file(
                    file_id=acme_id,
                    firm_id=FIRM_A_ID,
                    client_id=ACME_HEALTHCARE_ID,
                    membership_id=ALICE_MEMBERSHIP_ID,
                ),
                _stored_file(
                    file_id=northstar_id,
                    firm_id=FIRM_B_ID,
                    client_id=NORTHSTAR_RETAIL_ID,
                    membership_id=BOB_MEMBERSHIP_ID,
                ),
            ]
        )

    with Session(app_engine) as session, session.begin():
        assert list(session.scalars(select(StoredFile.id))) == []

    alice = _principal(
        user_id=ALICE_ID,
        membership_id=ALICE_MEMBERSHIP_ID,
        firm_id=FIRM_A_ID,
        role=FirmRole.CONSULTANT,
    )
    bob = _principal(
        user_id=BOB_ID,
        membership_id=BOB_MEMBERSHIP_ID,
        firm_id=FIRM_B_ID,
        role=FirmRole.CONSULTANT,
    )
    cases = (
        (alice, APOLLO_FINANCE_ID, {apollo_id}),
        (alice, ACME_HEALTHCARE_ID, {acme_id}),
        (bob, NORTHSTAR_RETAIL_ID, {northstar_id}),
    )

    def visible_ids(case) -> set[UUID]:
        principal, client_id, _ = case
        with Session(app_engine) as session, session.begin():
            AccessControlService.authorize_client(
                session,
                principal=principal,
                client_id=client_id,
                permission=Permission.FILE_READ,
            )
            return set(session.scalars(select(StoredFile.id)))

    for case in cases * 10:
        assert visible_ids(case) == case[2]

    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = [executor.submit(visible_ids, case) for case in cases * 8]
        for future, case in zip(futures, cases * 8, strict=True):
            assert future.result() == case[2]
