from __future__ import annotations

import hashlib
import io
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from fixtures.authorization import MultiIdentityStytchGateway
from fixtures.storage import FakeObjectStorageGateway
from fixtures.tenant_foundation import ACME_HEALTHCARE_ID, APOLLO_FINANCE_ID, NORTHSTAR_RETAIL_ID
from pydantic import SecretStr
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from privexa_api.clients.enums import ClientWorkspaceStatus
from privexa_api.clients.models import ClientWorkspace
from privexa_api.config import Settings
from privexa_api.db.session import build_session_factory
from privexa_api.files.models import StoredFile
from privexa_api.files.service import LOGGER
from privexa_api.main import create_app

PDF_BYTES = b"%PDF-1.7\nPrivexa secure file boundary\n%%EOF\n"
PDF_SHA256 = hashlib.sha256(PDF_BYTES).hexdigest()
ORIGIN = "http://localhost:3000"


def _build_client(app_engine: Engine) -> tuple[TestClient, FakeObjectStorageGateway]:
    storage = FakeObjectStorageGateway()
    settings = Settings(
        APP_DATABASE_URL="postgresql+psycopg://unused",
        STYTCH_PROJECT_ID="project-test-privexa",
        STYTCH_SECRET=SecretStr("secret-test-privexa"),
        PRIVEXA_ENVIRONMENT="test",
        PRIVEXA_WEB_ORIGIN=ORIGIN,
        OBJECT_STORAGE_BUCKET=storage.bucket,
        MAX_FILE_UPLOAD_SIZE_BYTES=1024,
    )
    app = create_app(
        settings=settings,
        stytch_gateway=MultiIdentityStytchGateway(),
        object_storage_gateway=storage,
        session_factory=build_session_factory(app_engine),
    )
    return TestClient(app), storage


def _upload_request(**overrides) -> dict[str, object]:
    payload: dict[str, object] = {
        "original_filename": "Apollo audit report.pdf",
        "mime_type": "application/pdf",
        "size_bytes": len(PDF_BYTES),
        "checksum_sha256": PDF_SHA256,
    }
    payload.update(overrides)
    return payload


def _post(client: TestClient, path: str, *, json=None):
    return client.post(path, json=json, headers={"Origin": ORIGIN})


def _activate(client: TestClient, client_id=APOLLO_FINANCE_ID) -> None:
    response = client.put(
        f"/v1/application-context/active-client/{client_id}",
        headers={"Origin": ORIGIN},
    )
    assert response.status_code == 200, response.text


def _create_pending(
    client: TestClient,
    storage: FakeObjectStorageGateway,
    client_id=APOLLO_FINANCE_ID,
) -> str:
    _activate(client, client_id)
    response = _post(client, f"/v1/clients/{client_id}/files/uploads", json=_upload_request())
    assert response.status_code == 201, response.text
    assert response.json()["file"]["status"] == "PENDING_UPLOAD"
    assert response.json()["file"]["sensitivity_level"] == "SENSITIVE"
    assert response.headers["cache-control"] == "no-store"
    assert "storage_bucket" not in response.text
    assert "storage_key" not in response.text
    assert "secret-test-privexa" not in response.text
    assert storage.upload_locations[-1].key.startswith("staging/firms/")
    return response.json()["file"]["file_id"]


def test_complete_download_and_delete_live_service_flow(
    tenant_data,
    app_engine: Engine,
) -> None:
    client, storage = _build_client(app_engine)
    client.cookies.set("stytch_session", "alice-token")
    file_id = _create_pending(client, storage)
    upload_location = storage.upload_locations[-1]
    storage.upload(
        location=upload_location,
        content=PDF_BYTES,
        mime_type="application/pdf",
        sha256=PDF_SHA256,
    )

    completed = _post(client, f"/v1/clients/{APOLLO_FINANCE_ID}/files/{file_id}/complete")
    repeated = _post(client, f"/v1/clients/{APOLLO_FINANCE_ID}/files/{file_id}/complete")
    metadata = client.get(f"/v1/clients/{APOLLO_FINANCE_ID}/files/{file_id}")
    download = _post(client, f"/v1/clients/{APOLLO_FINANCE_ID}/files/{file_id}/download")

    assert completed.status_code == repeated.status_code == 200
    assert completed.json()["status"] == repeated.json()["status"] == "AVAILABLE"
    assert metadata.status_code == 200
    assert download.status_code == 200
    assert download.json()["url"].startswith("https://storage.test/download/")
    assert storage.download_locations[-1].key.endswith(f"/files/{file_id}/original")

    deleted = client.delete(
        f"/v1/clients/{APOLLO_FINANCE_ID}/files/{file_id}",
        headers={"Origin": ORIGIN},
    )
    repeated_delete = client.delete(
        f"/v1/clients/{APOLLO_FINANCE_ID}/files/{file_id}",
        headers={"Origin": ORIGIN},
    )
    after_delete = _post(
        client,
        f"/v1/clients/{APOLLO_FINANCE_ID}/files/{file_id}/download",
    )

    assert deleted.status_code == repeated_delete.status_code == 204
    assert after_delete.status_code == 409
    assert after_delete.json()["code"] == "FILE_NOT_AVAILABLE"
    assert not storage.objects


@pytest.mark.security
@pytest.mark.tenant_isolation
def test_cross_client_and_cross_firm_file_identifiers_do_not_leak(
    tenant_data,
    app_engine: Engine,
) -> None:
    client, storage = _build_client(app_engine)
    client.cookies.set("stytch_session", "alice-token")
    file_id = _create_pending(client, storage)

    same_firm_other_client = client.get(f"/v1/clients/{ACME_HEALTHCARE_ID}/files/{file_id}")
    same_firm_download = _post(
        client,
        f"/v1/clients/{ACME_HEALTHCARE_ID}/files/{file_id}/download",
    )
    same_firm_complete = _post(
        client,
        f"/v1/clients/{ACME_HEALTHCARE_ID}/files/{file_id}/complete",
    )
    same_firm_delete = client.delete(
        f"/v1/clients/{ACME_HEALTHCARE_ID}/files/{file_id}",
        headers={"Origin": ORIGIN},
    )
    client.cookies.set("stytch_session", "bob-token")
    _activate(client, NORTHSTAR_RETAIL_ID)
    cross_firm = client.get(f"/v1/clients/{NORTHSTAR_RETAIL_ID}/files/{file_id}")
    cross_firm_download = _post(
        client,
        f"/v1/clients/{NORTHSTAR_RETAIL_ID}/files/{file_id}/download",
    )
    cross_firm_complete = _post(
        client,
        f"/v1/clients/{NORTHSTAR_RETAIL_ID}/files/{file_id}/complete",
    )
    cross_firm_delete = client.delete(
        f"/v1/clients/{NORTHSTAR_RETAIL_ID}/files/{file_id}",
        headers={"Origin": ORIGIN},
    )
    random_delete = client.delete(
        f"/v1/clients/{NORTHSTAR_RETAIL_ID}/files/00000000-0000-4000-8000-999999999997",
        headers={"Origin": ORIGIN},
    )

    for response in (
        same_firm_other_client,
        same_firm_download,
        same_firm_complete,
        same_firm_delete,
        cross_firm,
        cross_firm_download,
        cross_firm_complete,
        cross_firm_delete,
        random_delete,
    ):
        assert response.status_code == 404
        assert response.json()["code"] == "RESOURCE_NOT_FOUND"
    assert not storage.download_locations


@pytest.mark.security
@pytest.mark.tenant_isolation
def test_same_user_must_switch_before_another_authorized_clients_file_is_available(
    tenant_data,
    app_engine: Engine,
) -> None:
    client, storage = _build_client(app_engine)
    client.cookies.set("stytch_session", "alice-token")
    apollo_file_id = _create_pending(client, storage)
    random_file_id = "00000000-0000-4000-8000-999999999998"

    _activate(client, ACME_HEALTHCARE_ID)
    wrong_client_path = client.get(f"/v1/clients/{APOLLO_FINANCE_ID}/files/{apollo_file_id}")
    known_other_client_id = client.get(f"/v1/clients/{ACME_HEALTHCARE_ID}/files/{apollo_file_id}")
    known_other_client_delete = client.delete(
        f"/v1/clients/{ACME_HEALTHCARE_ID}/files/{apollo_file_id}",
        headers={"Origin": ORIGIN},
    )
    nonexistent_id = client.get(f"/v1/clients/{ACME_HEALTHCARE_ID}/files/{random_file_id}")

    def public_problem(response) -> dict[str, object]:
        body = response.json()
        body.pop("request_id")
        return body

    for response in (
        wrong_client_path,
        known_other_client_id,
        known_other_client_delete,
        nonexistent_id,
    ):
        assert response.status_code == 404
        assert response.headers["cache-control"] == "no-store"
    assert public_problem(wrong_client_path) == public_problem(known_other_client_id)
    assert public_problem(known_other_client_delete) == public_problem(nonexistent_id)
    assert public_problem(known_other_client_id) == public_problem(nonexistent_id)

    _activate(client, APOLLO_FINANCE_ID)
    allowed_after_explicit_switch = client.get(
        f"/v1/clients/{APOLLO_FINANCE_ID}/files/{apollo_file_id}"
    )
    assert allowed_after_explicit_switch.status_code == 200
    assert allowed_after_explicit_switch.json()["file_id"] == apollo_file_id


@pytest.mark.security
@pytest.mark.tenant_isolation
def test_create_ownership_forgery_is_rejected_without_persistence(
    tenant_data,
    app_engine: Engine,
    owner_engine: Engine,
) -> None:
    client, storage = _build_client(app_engine)
    client.cookies.set("stytch_session", "alice-token")
    _activate(client, ACME_HEALTHCARE_ID)

    with Session(owner_engine) as session:
        before = session.scalar(select(func.count()).select_from(StoredFile))
    forged = _post(
        client,
        f"/v1/clients/{ACME_HEALTHCARE_ID}/files/uploads",
        json=_upload_request(client_id=str(APOLLO_FINANCE_ID)),
    )
    with Session(owner_engine) as session:
        after = session.scalar(select(func.count()).select_from(StoredFile))

    assert forged.status_code == 422
    assert before == after
    assert storage.upload_locations == []

    valid = _post(
        client,
        f"/v1/clients/{ACME_HEALTHCARE_ID}/files/uploads",
        json=_upload_request(),
    )
    assert valid.status_code == 201
    with Session(owner_engine) as session:
        persisted = session.get(StoredFile, UUID(valid.json()["file"]["file_id"]))
    assert persisted is not None
    assert persisted.client_id == ACME_HEALTHCARE_ID


@pytest.mark.security
@pytest.mark.tenant_isolation
def test_scoped_file_miss_records_one_safe_investigable_event(
    tenant_data,
    app_engine: Engine,
) -> None:
    client, storage = _build_client(app_engine)
    client.cookies.set("stytch_session", "alice-token")
    apollo_file_id = _create_pending(client, storage)
    _activate(client, ACME_HEALTHCARE_ID)
    output = io.StringIO()
    handler = logging.StreamHandler(output)
    LOGGER.addHandler(handler)

    try:
        response = client.get(f"/v1/clients/{ACME_HEALTHCARE_ID}/files/{apollo_file_id}")
    finally:
        LOGGER.removeHandler(handler)

    events = [json.loads(line) for line in output.getvalue().splitlines() if line]
    assert response.status_code == 404
    assert events == [
        {
            "client_id": str(ACME_HEALTHCARE_ID),
            "decision": "DENY",
            "event": "file.resource_unavailable",
            "file_id": apollo_file_id,
            "firm_id": str(tenant_data.firm_a.id),
            "membership_id": str(tenant_data.alice_membership.id),
            "operation": "read_metadata",
            "originating_channel": "WEB",
            "principal_id": str(tenant_data.alice.id),
            "reason_code": "RESOURCE_NOT_FOUND",
            "request_id": response.json()["request_id"],
            "trace_id": None,
        }
    ]
    assert "alice-token" not in output.getvalue()
    assert "Apollo audit report.pdf" not in output.getvalue()


def test_pending_download_and_storage_delete_failure_preserve_lifecycle(
    tenant_data,
    app_engine: Engine,
) -> None:
    client, storage = _build_client(app_engine)
    client.cookies.set("stytch_session", "alice-token")
    file_id = _create_pending(client, storage)

    pending_download = _post(
        client,
        f"/v1/clients/{APOLLO_FINANCE_ID}/files/{file_id}/download",
    )
    assert pending_download.status_code == 409
    assert pending_download.json()["code"] == "FILE_NOT_AVAILABLE"

    storage.upload(
        location=storage.upload_locations[-1],
        content=PDF_BYTES,
        mime_type="application/pdf",
        sha256=PDF_SHA256,
    )
    completed = _post(
        client,
        f"/v1/clients/{APOLLO_FINANCE_ID}/files/{file_id}/complete",
    )
    assert completed.status_code == 200

    storage.fail_delete = True
    failed_delete = client.delete(
        f"/v1/clients/{APOLLO_FINANCE_ID}/files/{file_id}",
        headers={"Origin": ORIGIN},
    )
    metadata_after_failure = client.get(f"/v1/clients/{APOLLO_FINANCE_ID}/files/{file_id}")
    assert failed_delete.status_code == 503
    assert failed_delete.json()["code"] == "STORAGE_TEMPORARILY_UNAVAILABLE"
    assert metadata_after_failure.json()["status"] == "AVAILABLE"

    storage.fail_delete = False
    storage.objects.clear()
    missing_object_delete = client.delete(
        f"/v1/clients/{APOLLO_FINANCE_ID}/files/{file_id}",
        headers={"Origin": ORIGIN},
    )
    deleted_metadata = client.get(f"/v1/clients/{APOLLO_FINANCE_ID}/files/{file_id}")
    assert missing_object_delete.status_code == 204
    assert deleted_metadata.status_code == 404


@pytest.mark.security
def test_read_only_member_cannot_create_or_delete_files(
    tenant_data,
    app_engine: Engine,
) -> None:
    client, storage = _build_client(app_engine)
    client.cookies.set("stytch_session", "alice-token")
    file_id = _create_pending(client, storage, ACME_HEALTHCARE_ID)

    client.cookies.set("stytch_session", "mark-token")
    _activate(client, ACME_HEALTHCARE_ID)
    create = _post(
        client,
        f"/v1/clients/{ACME_HEALTHCARE_ID}/files/uploads",
        json=_upload_request(),
    )
    delete = client.delete(
        f"/v1/clients/{ACME_HEALTHCARE_ID}/files/{file_id}",
        headers={"Origin": ORIGIN},
    )

    assert create.status_code == delete.status_code == 403
    assert create.json()["code"] == delete.json()["code"] == "FORBIDDEN"


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"size_bytes": 0}, "INVALID_FILE_SIZE"),
        ({"size_bytes": 2048}, "FILE_TOO_LARGE"),
        ({"mime_type": "application/x-executable"}, "UNSUPPORTED_FILE_TYPE"),
        ({"mime_type": "application/pdf; charset=utf-8"}, "UNSUPPORTED_FILE_TYPE"),
        ({"original_filename": "../../secret.pdf"}, "INVALID_FILENAME"),
        ({"original_filename": "x\x00.pdf"}, "INVALID_FILENAME"),
        ({"original_filename": "a" * 256 + ".pdf"}, "INVALID_FILENAME"),
        ({"original_filename": "report.txt"}, "FILE_TYPE_MISMATCH"),
        ({"checksum_sha256": "0" * 63 + "z"}, "INVALID_FILE_CHECKSUM"),
        ({"sensitivity_level": "STANDARD"}, "INVALID_FILE_SENSITIVITY"),
    ],
)
def test_upload_validation_rejects_unsafe_metadata(
    tenant_data,
    app_engine: Engine,
    overrides: dict[str, object],
    code: str,
) -> None:
    client, _ = _build_client(app_engine)
    client.cookies.set("stytch_session", "alice-token")
    _activate(client)

    response = _post(
        client,
        f"/v1/clients/{APOLLO_FINANCE_ID}/files/uploads",
        json=_upload_request(**overrides),
    )

    assert response.status_code == 422
    assert response.json()["code"] == code


def test_completion_missing_and_wrong_object_are_not_made_available(
    tenant_data,
    app_engine: Engine,
) -> None:
    client, storage = _build_client(app_engine)
    client.cookies.set("stytch_session", "alice-token")
    missing_id = _create_pending(client, storage)

    missing = _post(
        client,
        f"/v1/clients/{APOLLO_FINANCE_ID}/files/{missing_id}/complete",
    )
    assert missing.status_code == 409
    assert missing.json()["code"] == "UPLOAD_NOT_READY"

    wrong_id = _create_pending(client, storage)
    storage.upload(
        location=storage.upload_locations[-1],
        content=b"wrong bytes",
        mime_type="application/pdf",
        sha256="0" * 64,
    )
    wrong = _post(client, f"/v1/clients/{APOLLO_FINANCE_ID}/files/{wrong_id}/complete")
    metadata = client.get(f"/v1/clients/{APOLLO_FINANCE_ID}/files/{wrong_id}")

    assert wrong.status_code == 409
    assert wrong.json()["code"] == "FILE_UPLOAD_FAILED"
    assert metadata.json()["status"] == "FAILED"


def test_expired_upload_cannot_be_completed(
    tenant_data,
    app_engine: Engine,
    owner_engine: Engine,
) -> None:
    client, storage = _build_client(app_engine)
    client.cookies.set("stytch_session", "alice-token")
    file_id = _create_pending(client, storage)
    storage.upload(
        location=storage.upload_locations[-1],
        content=PDF_BYTES,
        mime_type="application/pdf",
        sha256=PDF_SHA256,
    )
    with Session(owner_engine) as session, session.begin():
        stored_file = session.get(StoredFile, UUID(file_id))
        assert stored_file is not None
        stored_file.upload_expires_at = datetime.now(UTC) - timedelta(hours=1)

    expired = _post(
        client,
        f"/v1/clients/{APOLLO_FINANCE_ID}/files/{file_id}/complete",
    )
    metadata = client.get(f"/v1/clients/{APOLLO_FINANCE_ID}/files/{file_id}")

    assert expired.status_code == 409
    assert expired.json()["code"] == "FILE_UPLOAD_EXPIRED"
    assert metadata.json()["status"] == "FAILED"
    assert not storage.objects


def test_storage_failure_is_safe_and_signed_urls_are_not_logged(
    tenant_data,
    app_engine: Engine,
) -> None:
    client, storage = _build_client(app_engine)
    client.cookies.set("stytch_session", "alice-token")
    output = io.StringIO()
    handler = logging.StreamHandler(output)
    LOGGER.addHandler(handler)
    try:
        file_id = _create_pending(client, storage)
        storage.fail_head = True
        response = _post(
            client,
            f"/v1/clients/{APOLLO_FINANCE_ID}/files/{file_id}/complete",
        )
    finally:
        LOGGER.removeHandler(handler)

    assert response.status_code == 503
    logged = output.getvalue()
    assert "https://storage.test" not in logged
    assert "Apollo audit report.pdf" not in logged
    assert PDF_SHA256 not in logged


def test_signing_and_copy_provider_failures_are_safe_and_retryable(
    tenant_data,
    app_engine: Engine,
    owner_engine: Engine,
) -> None:
    client, storage = _build_client(app_engine)
    client.cookies.set("stytch_session", "alice-token")
    _activate(client)
    storage.fail_upload_sign = True
    failed_initiation = _post(
        client,
        f"/v1/clients/{APOLLO_FINANCE_ID}/files/uploads",
        json=_upload_request(),
    )
    with Session(owner_engine) as session:
        stored_count = session.scalar(select(func.count()).select_from(StoredFile))

    assert failed_initiation.status_code == 503
    assert failed_initiation.json()["code"] == "STORAGE_TEMPORARILY_UNAVAILABLE"
    assert "FAKE_UPLOAD_SIGN_FAILURE" not in failed_initiation.text
    assert stored_count == 0

    storage.fail_upload_sign = False
    file_id = _create_pending(client, storage)
    storage.upload(
        location=storage.upload_locations[-1],
        content=PDF_BYTES,
        mime_type="application/pdf",
        sha256=PDF_SHA256,
    )
    storage.fail_copy = True
    failed_copy = _post(
        client,
        f"/v1/clients/{APOLLO_FINANCE_ID}/files/{file_id}/complete",
    )
    pending = client.get(f"/v1/clients/{APOLLO_FINANCE_ID}/files/{file_id}")
    assert failed_copy.status_code == 503
    assert "FAKE_COPY_FAILURE" not in failed_copy.text
    assert pending.json()["status"] == "PENDING_UPLOAD"

    storage.fail_copy = False
    completed = _post(
        client,
        f"/v1/clients/{APOLLO_FINANCE_ID}/files/{file_id}/complete",
    )
    assert completed.status_code == 200

    storage.fail_download_sign = True
    failed_download = _post(
        client,
        f"/v1/clients/{APOLLO_FINANCE_ID}/files/{file_id}/download",
    )
    assert failed_download.status_code == 503
    assert "FAKE_DOWNLOAD_SIGN_FAILURE" not in failed_download.text


def test_callers_cannot_supply_storage_location_fields(
    tenant_data,
    app_engine: Engine,
) -> None:
    client, _ = _build_client(app_engine)
    client.cookies.set("stytch_session", "alice-token")
    _activate(client)
    payload = _upload_request(storage_key="objects/foreign", storage_bucket="foreign")

    response = _post(
        client,
        f"/v1/clients/{APOLLO_FINANCE_ID}/files/uploads",
        json=payload,
    )

    assert response.status_code == 422


@pytest.mark.parametrize(
    "field_value",
    [
        {"firm_id": "00000000-0000-4000-8000-000000000101"},
        {"client_id": str(ACME_HEALTHCARE_ID)},
        {"storage_key": "objects/foreign"},
        {"storage_bucket": "foreign"},
        {"object_key": "objects/foreign"},
        {"object_path": "../../foreign"},
        {"prefix": "firms/foreign"},
        {"status": "AVAILABLE"},
        {"created_by_membership_id": "00000000-0000-4000-8000-000000000004"},
        {"deleted_at": "2026-08-21T00:00:00Z"},
    ],
)
def test_upload_request_rejects_tenant_storage_and_lifecycle_mass_assignment(
    tenant_data,
    app_engine: Engine,
    field_value: dict[str, object],
) -> None:
    client, storage = _build_client(app_engine)
    client.cookies.set("stytch_session", "alice-token")
    _activate(client)

    response = _post(
        client,
        f"/v1/clients/{APOLLO_FINANCE_ID}/files/uploads",
        json=_upload_request(**field_value),
    )

    assert response.status_code == 422
    assert not storage.upload_locations


@pytest.mark.parametrize(
    "size",
    [-1, 0, 1025, 2**63, "1024", None],
)
def test_upload_size_invalid_boundaries_and_types_fail_closed(
    tenant_data,
    app_engine: Engine,
    size: object,
) -> None:
    client, storage = _build_client(app_engine)
    client.cookies.set("stytch_session", "alice-token")
    _activate(client)

    response = _post(
        client,
        f"/v1/clients/{APOLLO_FINANCE_ID}/files/uploads",
        json=_upload_request(size_bytes=size),
    )

    assert response.status_code == 422
    assert not storage.upload_locations


@pytest.mark.parametrize("size", [1023, 1024])
def test_upload_size_configured_boundary_is_inclusive(
    tenant_data,
    app_engine: Engine,
    size: int,
) -> None:
    client, storage = _build_client(app_engine)
    client.cookies.set("stytch_session", "alice-token")
    _activate(client)

    response = _post(
        client,
        f"/v1/clients/{APOLLO_FINANCE_ID}/files/uploads",
        json=_upload_request(size_bytes=size),
    )

    assert response.status_code == 201
    assert response.json()["file"]["size_bytes"] == size
    assert len(storage.upload_locations) == 1


def test_file_routes_reject_stale_auth_forged_headers_and_malformed_ids(
    tenant_data,
    app_engine: Engine,
) -> None:
    client, storage = _build_client(app_engine)
    upload_path = f"/v1/clients/{APOLLO_FINANCE_ID}/files/uploads"

    missing = _post(client, upload_path, json=_upload_request())
    client.cookies.set("stytch_session", "expired-token")
    expired = _post(client, upload_path, json=_upload_request())
    client.cookies.set("stytch_session", "invalid-token")
    invalid = _post(client, upload_path, json=_upload_request())
    client.cookies.set("stytch_session", "bob-token")
    _activate(client, NORTHSTAR_RETAIL_ID)
    forged = client.post(
        upload_path,
        json=_upload_request(),
        headers={
            "Origin": ORIGIN,
            "X-Firm-ID": "00000000-0000-4000-8000-000000000001",
            "X-Client-ID": str(APOLLO_FINANCE_ID),
            "X-User-ID": "00000000-0000-4000-8000-000000000003",
        },
    )
    client.cookies.set("stytch_session", "alice-token")
    _activate(client)
    malformed_client = client.get("/v1/clients/not-a-uuid/files/not-a-uuid")
    malformed_file = client.get(f"/v1/clients/{APOLLO_FINANCE_ID}/files/not-a-uuid")
    random_file = client.get(
        f"/v1/clients/{APOLLO_FINANCE_ID}/files/00000000-0000-4000-8000-999999999999"
    )

    assert missing.status_code == expired.status_code == invalid.status_code == 401
    assert forged.status_code == 404
    assert malformed_client.status_code == malformed_file.status_code == 422
    assert random_file.status_code == 404
    assert not storage.upload_locations


def test_unsupported_methods_do_not_expose_generic_metadata_mutation(
    tenant_data,
    app_engine: Engine,
) -> None:
    client, storage = _build_client(app_engine)
    client.cookies.set("stytch_session", "alice-token")
    file_id = _create_pending(client, storage)
    path = f"/v1/clients/{APOLLO_FINANCE_ID}/files/{file_id}"

    put = client.put(path, json={"status": "AVAILABLE"}, headers={"Origin": ORIGIN})
    patch = client.patch(path, json={"status": "AVAILABLE"}, headers={"Origin": ORIGIN})
    head = client.head(path)

    assert put.status_code == patch.status_code == head.status_code == 405
    metadata = client.get(path)
    assert metadata.status_code == 200
    assert metadata.json()["status"] == "PENDING_UPLOAD"


def test_restricted_sensitivity_survives_lifecycle_and_cannot_be_downgraded(
    tenant_data,
    app_engine: Engine,
) -> None:
    client, storage = _build_client(app_engine)
    client.cookies.set("stytch_session", "alice-token")
    _activate(client)
    initiated = _post(
        client,
        f"/v1/clients/{APOLLO_FINANCE_ID}/files/uploads",
        json=_upload_request(sensitivity_level="RESTRICTED"),
    )
    assert initiated.status_code == 201
    file_id = initiated.json()["file"]["file_id"]
    assert initiated.json()["file"]["sensitivity_level"] == "RESTRICTED"
    storage.upload(
        location=storage.upload_locations[-1],
        content=PDF_BYTES,
        mime_type="application/pdf",
        sha256=PDF_SHA256,
    )

    completed = _post(
        client,
        f"/v1/clients/{APOLLO_FINANCE_ID}/files/{file_id}/complete",
    )
    metadata = client.get(f"/v1/clients/{APOLLO_FINANCE_ID}/files/{file_id}")
    downgrade = client.patch(
        f"/v1/clients/{APOLLO_FINANCE_ID}/files/{file_id}",
        json={"sensitivity_level": "STANDARD"},
        headers={"Origin": ORIGIN},
    )

    assert completed.json()["sensitivity_level"] == "RESTRICTED"
    assert metadata.json()["sensitivity_level"] == "RESTRICTED"
    assert downgrade.status_code == 405


def test_concurrent_upload_initiation_and_completion_remain_isolated_and_idempotent(
    tenant_data,
    app_engine: Engine,
) -> None:
    client, storage = _build_client(app_engine)

    def initiate(index: int) -> tuple[str, int]:
        worker = TestClient(client.app)
        worker.cookies.set("stytch_session", "alice-token")
        _activate(worker)
        response = _post(
            worker,
            f"/v1/clients/{APOLLO_FINANCE_ID}/files/uploads",
            json=_upload_request(original_filename=f"concurrent-{index}.pdf"),
        )
        return response.json()["file"]["file_id"], response.status_code

    with ThreadPoolExecutor(max_workers=6) as executor:
        initiated = list(executor.map(initiate, range(12)))

    file_ids = {file_id for file_id, _ in initiated}
    assert {status for _, status in initiated} == {201}
    assert len(file_ids) == 12
    assert len({location.key for location in storage.upload_locations}) == 12

    file_id = next(iter(file_ids))
    upload_location = next(
        location for location in storage.upload_locations if f"/files/{file_id}/" in location.key
    )
    storage.upload(
        location=upload_location,
        content=PDF_BYTES,
        mime_type="application/pdf",
        sha256=PDF_SHA256,
    )

    def complete(_: int) -> tuple[int, str]:
        worker = TestClient(client.app)
        worker.cookies.set("stytch_session", "alice-token")
        _activate(worker)
        response = _post(
            worker,
            f"/v1/clients/{APOLLO_FINANCE_ID}/files/{file_id}/complete",
        )
        return response.status_code, response.json()["status"]

    with ThreadPoolExecutor(max_workers=6) as executor:
        outcomes = list(executor.map(complete, range(8)))

    assert set(outcomes) == {(200, "AVAILABLE")}
    canonical_objects = [key for key in storage.objects if key[1].endswith("/original")]
    assert len(canonical_objects) == 1


def test_inactive_client_cannot_receive_new_file_metadata(
    tenant_data,
    owner_engine: Engine,
    app_engine: Engine,
) -> None:
    with Session(owner_engine) as session, session.begin():
        client_workspace = session.get(ClientWorkspace, APOLLO_FINANCE_ID)
        assert client_workspace is not None
        client_workspace.status = ClientWorkspaceStatus.INACTIVE

    client, storage = _build_client(app_engine)
    client.cookies.set("stytch_session", "alice-token")
    response = client.put(
        f"/v1/application-context/active-client/{APOLLO_FINANCE_ID}",
        headers={"Origin": ORIGIN},
    )

    assert response.status_code == 404
    assert response.json()["code"] == "RESOURCE_NOT_FOUND"
    file_response = _post(
        client,
        f"/v1/clients/{APOLLO_FINANCE_ID}/files/uploads",
        json=_upload_request(),
    )

    assert file_response.status_code != 201
    assert not storage.upload_locations


def test_delete_download_race_never_returns_server_error_or_resurrects_object(
    tenant_data,
    app_engine: Engine,
) -> None:
    client, storage = _build_client(app_engine)
    client.cookies.set("stytch_session", "alice-token")
    file_id = _create_pending(client, storage)
    storage.upload(
        location=storage.upload_locations[-1],
        content=PDF_BYTES,
        mime_type="application/pdf",
        sha256=PDF_SHA256,
    )
    assert (
        _post(
            client,
            f"/v1/clients/{APOLLO_FINANCE_ID}/files/{file_id}/complete",
        ).status_code
        == 200
    )

    def download(_: int):
        worker = TestClient(client.app)
        worker.cookies.set("stytch_session", "alice-token")
        _activate(worker)
        return _post(
            worker,
            f"/v1/clients/{APOLLO_FINANCE_ID}/files/{file_id}/download",
        )

    def delete():
        worker = TestClient(client.app)
        worker.cookies.set("stytch_session", "alice-token")
        _activate(worker)
        return worker.delete(
            f"/v1/clients/{APOLLO_FINANCE_ID}/files/{file_id}",
            headers={"Origin": ORIGIN},
        )

    with ThreadPoolExecutor(max_workers=9) as executor:
        download_futures = [executor.submit(download, index) for index in range(8)]
        delete_future = executor.submit(delete)
        downloads = [future.result() for future in download_futures]
        deleted = delete_future.result()

    assert deleted.status_code == 204
    assert {response.status_code for response in downloads}.issubset({200, 409})
    assert all(response.status_code < 500 for response in downloads)
    after = _post(
        client,
        f"/v1/clients/{APOLLO_FINANCE_ID}/files/{file_id}/download",
    )
    assert after.status_code == 409
    assert not storage.objects
