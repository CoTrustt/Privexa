from __future__ import annotations

import hashlib
import time
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import boto3
import httpx2 as httpx
import pytest
from botocore.client import Config
from botocore.exceptions import ClientError
from fastapi.testclient import TestClient
from fixtures.authorization import MultiIdentityStytchGateway
from fixtures.tenant_foundation import (
    ACME_HEALTHCARE_ID,
    APOLLO_FINANCE_ID,
    NORTHSTAR_RETAIL_ID,
)
from sqlalchemy import Engine

from privexa_api.config import Settings
from privexa_api.db.session import build_session_factory
from privexa_api.main import create_app
from privexa_api.storage.gateway import ObjectLocation
from privexa_api.storage.s3 import S3ObjectStorageGateway

PDF_BYTES = b"%PDF-1.7\nPrivexa real object-storage integration\n%%EOF\n"
PDF_SHA256 = hashlib.sha256(PDF_BYTES).hexdigest()
ORIGIN = "http://localhost:3000"


def _live_settings() -> Settings:
    settings = Settings()  # type: ignore[call-arg]
    if settings.object_storage_endpoint_url is None:
        pytest.skip("OBJECT_STORAGE_ENDPOINT_URL is required for storage integration")
    if settings.object_storage_access_key is None or settings.object_storage_secret_key is None:
        pytest.skip("Object-storage credentials are required for storage integration")
    return settings


def _live_storage(settings: Settings) -> S3ObjectStorageGateway:
    assert settings.object_storage_access_key is not None
    assert settings.object_storage_secret_key is not None
    return S3ObjectStorageGateway(
        bucket=settings.object_storage_bucket,
        region=settings.object_storage_region,
        endpoint_url=settings.object_storage_endpoint_url,
        access_key=settings.object_storage_access_key.get_secret_value(),
        secret_key=settings.object_storage_secret_key.get_secret_value(),
        addressing_style=settings.object_storage_addressing_style,
    )


@pytest.mark.security
@pytest.mark.storage_integration
def test_real_private_storage_vertical_slice_and_tenant_denial(
    tenant_data,
    app_engine: Engine,
    capsys: pytest.CaptureFixture[str],
) -> None:
    settings = _live_settings()
    app = create_app(
        settings=settings,
        stytch_gateway=MultiIdentityStytchGateway(),
        object_storage_gateway=_live_storage(settings),
        session_factory=build_session_factory(app_engine),
    )
    client = TestClient(app)
    client.cookies.set("stytch_session", "alice-token")
    assert (
        client.put(
            f"/v1/application-context/active-client/{APOLLO_FINANCE_ID}",
            headers={"Origin": ORIGIN},
        ).status_code
        == 200
    )

    initiated = client.post(
        f"/v1/clients/{APOLLO_FINANCE_ID}/files/uploads",
        json={
            "original_filename": "Apollo integration proof.pdf",
            "mime_type": "application/pdf",
            "size_bytes": len(PDF_BYTES),
            "checksum_sha256": PDF_SHA256,
        },
        headers={"Origin": ORIGIN},
    )
    assert initiated.status_code == 201, initiated.text
    payload = initiated.json()
    file_id = payload["file"]["file_id"]
    upload = payload["upload"]
    assert upload["method"] == "PUT"
    upload_query = parse_qs(urlparse(upload["url"]).query)
    assert upload_query["X-Amz-Expires"] == [str(settings.file_upload_url_ttl_seconds)]
    signed_headers = upload_query["X-Amz-SignedHeaders"][0].split(";")
    assert {
        "content-length",
        "content-type",
        "host",
        "if-none-match",
        "x-amz-checksum-sha256",
        "x-amz-meta-privexa-sha256",
    }.issubset(signed_headers)

    preflight = httpx.options(
        upload["url"],
        headers={
            "Origin": ORIGIN,
            "Access-Control-Request-Method": "PUT",
            "Access-Control-Request-Headers": ",".join(upload["required_headers"]),
        },
        timeout=10,
    )
    assert preflight.status_code in {200, 204}, preflight.text
    assert preflight.headers["access-control-allow-origin"] == ORIGIN
    assert httpx.get(upload["url"], timeout=10).status_code >= 400

    uploaded = httpx.put(
        upload["url"],
        content=PDF_BYTES,
        headers=upload["required_headers"],
        timeout=10,
    )
    assert uploaded.status_code == 200, uploaded.text

    completed = client.post(
        f"/v1/clients/{APOLLO_FINANCE_ID}/files/{file_id}/complete",
        headers={"Origin": ORIGIN},
    )
    assert completed.status_code == 200, completed.text
    assert completed.json()["status"] == "AVAILABLE"

    restarted_app = create_app(
        settings=settings,
        stytch_gateway=MultiIdentityStytchGateway(),
        object_storage_gateway=_live_storage(settings),
        session_factory=build_session_factory(app_engine),
    )
    restarted_client = TestClient(restarted_app)
    restarted_client.cookies.set("stytch_session", "alice-token")
    after_restart = restarted_client.get(f"/v1/clients/{APOLLO_FINANCE_ID}/files/{file_id}")
    assert after_restart.status_code == 200
    assert after_restart.json()["status"] == "AVAILABLE"

    signed_download = client.post(
        f"/v1/clients/{APOLLO_FINANCE_ID}/files/{file_id}/download",
        headers={"Origin": ORIGIN},
    )
    assert signed_download.status_code == 200, signed_download.text
    download_query = parse_qs(urlparse(signed_download.json()["url"]).query)
    assert download_query["X-Amz-Expires"] == [str(settings.file_download_url_ttl_seconds)]
    downloaded = httpx.get(signed_download.json()["url"], timeout=10)
    assert downloaded.status_code == 200
    assert downloaded.content == PDF_BYTES
    assert (
        httpx.put(signed_download.json()["url"], content=b"overwrite", timeout=10).status_code
        >= 400
    )

    assert settings.object_storage_endpoint_url is not None
    direct_object_url = (
        f"{settings.object_storage_endpoint_url.rstrip('/')}"
        f"/{settings.object_storage_bucket}/objects/firms/{tenant_data.firm_a.id}"
        f"/clients/{APOLLO_FINANCE_ID}/files/{file_id}/original"
    )
    unsigned = httpx.get(direct_object_url, timeout=10)
    assert unsigned.status_code in {401, 403}

    cross_client_metadata = client.get(f"/v1/clients/{ACME_HEALTHCARE_ID}/files/{file_id}")
    cross_client_download = client.post(
        f"/v1/clients/{ACME_HEALTHCARE_ID}/files/{file_id}/download",
        headers={"Origin": ORIGIN},
    )
    assert cross_client_metadata.status_code == 404
    assert cross_client_download.status_code == 404
    assert "url" not in cross_client_download.json()
    cross_client_delete = client.delete(
        f"/v1/clients/{ACME_HEALTHCARE_ID}/files/{file_id}",
        headers={"Origin": ORIGIN},
    )
    assert cross_client_delete.status_code == 404
    assert httpx.get(signed_download.json()["url"], timeout=10).content == PDF_BYTES

    client.cookies.set("stytch_session", "bob-token")
    assert (
        client.put(
            f"/v1/application-context/active-client/{NORTHSTAR_RETAIL_ID}",
            headers={"Origin": ORIGIN},
        ).status_code
        == 200
    )
    cross_firm_metadata = client.get(f"/v1/clients/{NORTHSTAR_RETAIL_ID}/files/{file_id}")
    cross_firm_download = client.post(
        f"/v1/clients/{NORTHSTAR_RETAIL_ID}/files/{file_id}/download",
        headers={"Origin": ORIGIN},
    )
    cross_firm_delete = client.delete(
        f"/v1/clients/{NORTHSTAR_RETAIL_ID}/files/{file_id}",
        headers={"Origin": ORIGIN},
    )
    assert {
        cross_firm_metadata.status_code,
        cross_firm_download.status_code,
        cross_firm_delete.status_code,
    } == {404}
    assert "url" not in cross_firm_download.json()
    assert httpx.get(signed_download.json()["url"], timeout=10).content == PDF_BYTES

    client.cookies.set("stytch_session", "alice-token")
    deleted = client.delete(
        f"/v1/clients/{APOLLO_FINANCE_ID}/files/{file_id}",
        headers={"Origin": ORIGIN},
    )
    assert deleted.status_code == 204
    new_download = client.post(
        f"/v1/clients/{APOLLO_FINANCE_ID}/files/{file_id}/download",
        headers={"Origin": ORIGIN},
    )
    assert new_download.status_code == 409
    assert httpx.get(signed_download.json()["url"], timeout=10).status_code == 404

    second = client.post(
        f"/v1/clients/{APOLLO_FINANCE_ID}/files/uploads",
        json={
            "original_filename": "Apollo size-bound proof.pdf",
            "mime_type": "application/pdf",
            "size_bytes": len(PDF_BYTES),
            "checksum_sha256": PDF_SHA256,
        },
        headers={"Origin": ORIGIN},
    )
    assert second.status_code == 201
    wrong_size_upload = httpx.put(
        second.json()["upload"]["url"],
        content=PDF_BYTES + b"x",
        headers=second.json()["upload"]["required_headers"],
        timeout=10,
    )
    assert wrong_size_upload.status_code >= 400
    pending_file_id = second.json()["file"]["file_id"]
    assert (
        client.delete(
            f"/v1/clients/{APOLLO_FINANCE_ID}/files/{pending_file_id}",
            headers={"Origin": ORIGIN},
        ).status_code
        == 204
    )
    runtime_output = "\n".join(capsys.readouterr())
    assert "X-Amz-Signature" not in runtime_output
    assert "X-Amz-Credential" not in runtime_output
    assert "privexa-local-app-password" not in runtime_output
    assert PDF_SHA256 not in runtime_output


@pytest.mark.security
@pytest.mark.storage_integration
def test_local_application_storage_identity_has_no_administrative_permissions() -> None:
    settings = _live_settings()
    assert settings.object_storage_access_key is not None
    assert settings.object_storage_secret_key is not None
    client = boto3.client(
        "s3",
        endpoint_url=settings.object_storage_endpoint_url,
        region_name=settings.object_storage_region,
        aws_access_key_id=settings.object_storage_access_key.get_secret_value(),
        aws_secret_access_key=settings.object_storage_secret_key.get_secret_value(),
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": settings.object_storage_addressing_style},
        ),
    )

    for operation in (
        client.list_buckets,
        lambda: client.list_objects_v2(Bucket=settings.object_storage_bucket),
        lambda: client.delete_bucket(Bucket=settings.object_storage_bucket),
    ):
        with pytest.raises(ClientError) as captured:
            operation()
        assert captured.value.response["Error"]["Code"] == "AccessDenied"


@pytest.mark.security
@pytest.mark.storage_integration
def test_real_presigned_upload_expires_at_provider_boundary() -> None:
    settings = _live_settings()
    storage = _live_storage(settings)
    expires_at = datetime.now(UTC) + timedelta(seconds=1)
    signed = storage.create_upload_url(
        location=ObjectLocation(
            bucket=settings.object_storage_bucket,
            key=f"staging/security-expiry-probes/{uuid4()}",
        ),
        content_type="application/pdf",
        size_bytes=len(PDF_BYTES),
        checksum_sha256=PDF_SHA256,
        expires_at=expires_at,
        ttl_seconds=1,
    )

    time.sleep(2.1)
    expired = httpx.put(
        signed.url,
        content=PDF_BYTES,
        headers=signed.required_headers,
        timeout=10,
    )
    assert expired.status_code == 403
