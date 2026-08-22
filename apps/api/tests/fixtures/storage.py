from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import uuid4

from privexa_api.storage.gateway import (
    ObjectHead,
    ObjectLocation,
    ObjectStorageOperationError,
    SignedStorageOperation,
)


@dataclass
class FakeObjectStorageGateway:
    bucket: str = "privexa-test"
    objects: dict[tuple[str, str], ObjectHead] = field(default_factory=dict)
    upload_locations: list[ObjectLocation] = field(default_factory=list)
    download_locations: list[ObjectLocation] = field(default_factory=list)
    fail_upload_sign: bool = False
    fail_download_sign: bool = False
    fail_head: bool = False
    fail_copy: bool = False
    fail_delete: bool = False

    def create_upload_url(
        self,
        *,
        location: ObjectLocation,
        content_type: str,
        size_bytes: int,
        checksum_sha256: str,
        expires_at: datetime,
        ttl_seconds: int,
    ) -> SignedStorageOperation:
        if self.fail_upload_sign:
            raise ObjectStorageOperationError("FAKE_UPLOAD_SIGN_FAILURE")
        self.upload_locations.append(location)
        return SignedStorageOperation(
            url=f"https://storage.test/upload/{uuid4()}",
            method="PUT",
            required_headers={
                "Content-Type": content_type,
                "x-amz-checksum-sha256": checksum_sha256,
                "If-None-Match": "*",
            },
            expires_at=expires_at,
        )

    def create_download_url(
        self,
        *,
        location: ObjectLocation,
        content_type: str,
        content_disposition: str,
        expires_at: datetime,
        ttl_seconds: int,
    ) -> SignedStorageOperation:
        if self.fail_download_sign:
            raise ObjectStorageOperationError("FAKE_DOWNLOAD_SIGN_FAILURE")
        self.download_locations.append(location)
        return SignedStorageOperation(
            url=f"https://storage.test/download/{uuid4()}",
            method="GET",
            required_headers={},
            expires_at=expires_at,
        )

    def head_object(self, *, location: ObjectLocation) -> ObjectHead | None:
        if self.fail_head:
            raise ObjectStorageOperationError("FAKE_HEAD_FAILURE")
        return self.objects.get((location.bucket, location.key))

    def copy_object(
        self,
        *,
        source: ObjectLocation,
        destination: ObjectLocation,
        content_type: str,
        checksum_sha256: str,
    ) -> None:
        if self.fail_copy:
            raise ObjectStorageOperationError("FAKE_COPY_FAILURE")
        head = self.objects.get((source.bucket, source.key))
        if head is None:
            raise ObjectStorageOperationError("FAKE_SOURCE_MISSING")
        self.objects[(destination.bucket, destination.key)] = ObjectHead(
            size_bytes=head.size_bytes,
            content_type=content_type,
            checksum_sha256=checksum_sha256,
            etag="fake-final-etag",
        )

    def delete_object(self, *, location: ObjectLocation) -> None:
        if self.fail_delete:
            raise ObjectStorageOperationError("FAKE_DELETE_FAILURE")
        self.objects.pop((location.bucket, location.key), None)

    def upload(
        self,
        *,
        location: ObjectLocation,
        content: bytes,
        mime_type: str,
        sha256: str,
    ) -> None:
        self.objects[(location.bucket, location.key)] = ObjectHead(
            size_bytes=len(content),
            content_type=mime_type,
            checksum_sha256=sha256,
            etag="fake-upload-etag",
        )
