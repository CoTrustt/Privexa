from __future__ import annotations

from uuid import UUID

import pytest
from pydantic import SecretStr, ValidationError

from privexa_api.config import Settings
from privexa_api.files.errors import FileValidationError
from privexa_api.files.policy import build_content_disposition, validate_file_metadata
from privexa_api.storage.gateway import ObjectLocation, ObjectStorageOperationError
from privexa_api.storage.keys import build_stored_file_keys
from privexa_api.storage.s3 import S3ObjectStorageGateway

FIRM_ID = UUID("00000000-0000-4000-8000-000000000001")
CLIENT_ID = UUID("00000000-0000-4000-8000-000000000002")
FILE_ID = UUID("00000000-0000-4000-8000-000000000003")


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "APP_DATABASE_URL": "postgresql+psycopg://unused",
        "STYTCH_PROJECT_ID": "project-test",
        "STYTCH_SECRET": SecretStr("secret-test"),
        "PRIVEXA_ENVIRONMENT": "test",
        "OBJECT_STORAGE_ENDPOINT_URL": None,
        "OBJECT_STORAGE_ACCESS_KEY": None,
        "OBJECT_STORAGE_SECRET_KEY": None,
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


def test_storage_keys_use_only_immutable_server_identifiers() -> None:
    keys = build_stored_file_keys(firm_id=FIRM_ID, client_id=CLIENT_ID, file_id=FILE_ID)

    assert keys.upload_key == (
        f"staging/firms/{FIRM_ID}/clients/{CLIENT_ID}/files/{FILE_ID}/upload"
    )
    assert keys.storage_key == (
        f"objects/firms/{FIRM_ID}/clients/{CLIENT_ID}/files/{FILE_ID}/original"
    )


def test_unicode_and_multiple_dot_filename_is_preserved_and_header_encoded() -> None:
    metadata = validate_file_metadata(
        original_filename="  ग्राहक.audit.final.PDF  ",
        mime_type="APPLICATION/PDF",
        size_bytes=10,
        checksum_sha256="A" * 64,
        max_size_bytes=100,
    )
    disposition = build_content_disposition(metadata.original_filename)

    assert metadata.original_filename == "ग्राहक.audit.final.PDF"
    assert metadata.mime_type == "application/pdf"
    assert metadata.checksum_sha256 == "a" * 64
    assert "\r" not in disposition and "\n" not in disposition
    assert "filename*=UTF-8''" in disposition


@pytest.mark.parametrize("filename", ["../audit.pdf", "..\\audit.pdf", "bad\r\n.pdf"])
def test_path_and_header_control_filenames_are_rejected(filename: str) -> None:
    with pytest.raises(FileValidationError):
        validate_file_metadata(
            original_filename=filename,
            mime_type="application/pdf",
            size_bytes=1,
            checksum_sha256="a" * 64,
            max_size_bytes=10,
        )


@pytest.mark.parametrize(
    "filename",
    [
        "<script>alert(1).pdf",
        "report%0d%0aX-Test-header.pdf",
        "CON.pdf",
        "  résumé-final.pdf  ",
    ],
)
def test_edge_case_filename_remains_metadata_and_has_safe_disposition(filename: str) -> None:
    metadata = validate_file_metadata(
        original_filename=filename,
        mime_type="application/pdf",
        size_bytes=1,
        checksum_sha256="a" * 64,
        max_size_bytes=10,
    )

    disposition = build_content_disposition(metadata.original_filename)
    assert "\r" not in disposition and "\n" not in disposition
    assert metadata.original_filename == filename.strip()


def test_filename_byte_limit_rejects_large_multibyte_input() -> None:
    with pytest.raises(FileValidationError):
        validate_file_metadata(
            original_filename="非" * 255 + ".pdf",
            mime_type="application/pdf",
            size_bytes=1,
            checksum_sha256="a" * 64,
            max_size_bytes=10,
        )


def test_s3_adapter_rejects_locations_outside_configured_boundary_before_io() -> None:
    storage = S3ObjectStorageGateway(
        bucket="privexa-test",
        region="us-east-1",
        endpoint_url="http://unreachable.invalid",
        access_key="test-access",
        secret_key="test-secret",
        addressing_style="path",
    )

    with pytest.raises(ObjectStorageOperationError):
        storage.head_object(location=ObjectLocation(bucket="other-tenant", key="objects/foreign"))
    with pytest.raises(ObjectStorageOperationError):
        storage.head_object(location=ObjectLocation(bucket="privexa-test", key="../foreign"))


def test_storage_configuration_rejects_partial_credentials_and_insecure_production() -> None:
    with pytest.raises(ValidationError):
        _settings(OBJECT_STORAGE_ACCESS_KEY=SecretStr("access-only"))

    with pytest.raises(ValidationError):
        _settings(
            PRIVEXA_ENVIRONMENT="production",
            OBJECT_STORAGE_BUCKET="privexa-production",
            OBJECT_STORAGE_ENDPOINT_URL="http://storage.internal",
        )


@pytest.mark.parametrize(
    "override",
    [
        {"OBJECT_STORAGE_BUCKET": ""},
        {"OBJECT_STORAGE_BUCKET": "Invalid_Bucket"},
        {"OBJECT_STORAGE_ENDPOINT_URL": "not-a-url"},
        {"OBJECT_STORAGE_ENDPOINT_URL": "http://user:password@storage.internal"},
        {"OBJECT_STORAGE_ENDPOINT_URL": "https://storage.internal?secret=value"},
        {"FILE_UPLOAD_URL_TTL_SECONDS": 59},
        {"FILE_UPLOAD_URL_TTL_SECONDS": 3601},
        {"FILE_DOWNLOAD_URL_TTL_SECONDS": 29},
        {"FILE_DOWNLOAD_URL_TTL_SECONDS": 901},
        {"MAX_FILE_UPLOAD_SIZE_BYTES": 0},
        {"MAX_FILE_UPLOAD_SIZE_BYTES": 5_368_709_121},
    ],
)
def test_storage_configuration_rejects_unsafe_limits(override: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        _settings(**override)
