from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True, slots=True)
class ObjectLocation:
    bucket: str
    key: str


@dataclass(frozen=True, slots=True)
class ObjectHead:
    size_bytes: int
    content_type: str
    checksum_sha256: str | None
    etag: str | None


@dataclass(frozen=True, slots=True)
class SignedStorageOperation:
    url: str
    method: str
    required_headers: dict[str, str]
    expires_at: datetime


class ObjectStorageOperationError(Exception):
    """The configured object store could not safely complete an operation."""


class ObjectStorageGateway(Protocol):
    def create_upload_url(
        self,
        *,
        location: ObjectLocation,
        content_type: str,
        size_bytes: int,
        checksum_sha256: str,
        expires_at: datetime,
        ttl_seconds: int,
    ) -> SignedStorageOperation: ...

    def create_download_url(
        self,
        *,
        location: ObjectLocation,
        content_type: str,
        content_disposition: str,
        expires_at: datetime,
        ttl_seconds: int,
    ) -> SignedStorageOperation: ...

    def head_object(self, *, location: ObjectLocation) -> ObjectHead | None: ...

    def copy_object(
        self,
        *,
        source: ObjectLocation,
        destination: ObjectLocation,
        content_type: str,
        checksum_sha256: str,
    ) -> None: ...

    def delete_object(self, *, location: ObjectLocation) -> None: ...
