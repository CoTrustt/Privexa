from __future__ import annotations

import base64
from datetime import datetime

import boto3
from botocore.client import Config
from botocore.exceptions import BotoCoreError, ClientError

from privexa_api.storage.gateway import (
    ObjectHead,
    ObjectLocation,
    ObjectStorageOperationError,
    SignedStorageOperation,
)


class S3ObjectStorageGateway:
    """S3 protocol adapter with one configured private-bucket boundary."""

    def __init__(
        self,
        *,
        bucket: str,
        region: str,
        endpoint_url: str | None,
        access_key: str | None,
        secret_key: str | None,
        addressing_style: str,
    ) -> None:
        self._bucket = bucket
        self._region = region
        self._endpoint_url = endpoint_url
        self._access_key = access_key
        self._secret_key = secret_key
        self._addressing_style = addressing_style
        self._client = None

    def _get_client(self):
        if self._client is None:
            self._client = boto3.client(
                "s3",
                region_name=self._region,
                endpoint_url=self._endpoint_url,
                aws_access_key_id=self._access_key,
                aws_secret_access_key=self._secret_key,
                config=Config(
                    signature_version="s3v4",
                    s3={"addressing_style": self._addressing_style},
                ),
            )
        return self._client

    def _validate_location(self, location: ObjectLocation) -> None:
        if location.bucket != self._bucket:
            raise ObjectStorageOperationError("OBJECT_STORAGE_BUCKET_OUTSIDE_BOUNDARY")
        if not location.key or location.key.startswith("/") or ".." in location.key.split("/"):
            raise ObjectStorageOperationError("OBJECT_STORAGE_KEY_INVALID")

    @staticmethod
    def _checksum_base64(checksum_sha256: str) -> str:
        try:
            return base64.b64encode(bytes.fromhex(checksum_sha256)).decode("ascii")
        except ValueError as error:
            raise ObjectStorageOperationError("OBJECT_STORAGE_CHECKSUM_INVALID") from error

    @staticmethod
    def _checksum_hex(value: str | None) -> str | None:
        if not value:
            return None
        try:
            return base64.b64decode(value, validate=True).hex()
        except ValueError:
            return None

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
        self._validate_location(location)
        checksum = self._checksum_base64(checksum_sha256)
        required_headers = {
            "Content-Type": content_type,
            "x-amz-checksum-sha256": checksum,
            "x-amz-meta-privexa-sha256": checksum_sha256,
            "If-None-Match": "*",
        }
        try:
            url = self._get_client().generate_presigned_url(
                "put_object",
                Params={
                    "Bucket": location.bucket,
                    "Key": location.key,
                    "ContentType": content_type,
                    "ContentLength": size_bytes,
                    "ChecksumSHA256": checksum,
                    "Metadata": {"privexa-sha256": checksum_sha256},
                    "IfNoneMatch": "*",
                },
                ExpiresIn=ttl_seconds,
                HttpMethod="PUT",
            )
        except (BotoCoreError, ClientError, ValueError) as error:
            raise ObjectStorageOperationError("OBJECT_STORAGE_SIGNING_FAILED") from error
        return SignedStorageOperation(
            url=url,
            method="PUT",
            required_headers=required_headers,
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
        self._validate_location(location)
        try:
            url = self._get_client().generate_presigned_url(
                "get_object",
                Params={
                    "Bucket": location.bucket,
                    "Key": location.key,
                    "ResponseContentType": content_type,
                    "ResponseContentDisposition": content_disposition,
                },
                ExpiresIn=ttl_seconds,
                HttpMethod="GET",
            )
        except (BotoCoreError, ClientError, ValueError) as error:
            raise ObjectStorageOperationError("OBJECT_STORAGE_SIGNING_FAILED") from error
        return SignedStorageOperation(
            url=url,
            method="GET",
            required_headers={},
            expires_at=expires_at,
        )

    def head_object(self, *, location: ObjectLocation) -> ObjectHead | None:
        self._validate_location(location)
        try:
            response = self._get_client().head_object(
                Bucket=location.bucket,
                Key=location.key,
                ChecksumMode="ENABLED",
            )
        except ClientError as error:
            status = error.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            code = error.response.get("Error", {}).get("Code")
            if status == 404 or code in {"404", "NoSuchKey", "NotFound"}:
                return None
            raise ObjectStorageOperationError("OBJECT_STORAGE_HEAD_FAILED") from error
        except BotoCoreError as error:
            raise ObjectStorageOperationError("OBJECT_STORAGE_HEAD_FAILED") from error
        checksum = self._checksum_hex(response.get("ChecksumSHA256"))
        if checksum is None:
            checksum = response.get("Metadata", {}).get("privexa-sha256")
        return ObjectHead(
            size_bytes=response["ContentLength"],
            content_type=response.get("ContentType", "application/octet-stream").lower(),
            checksum_sha256=checksum,
            etag=response.get("ETag", "").strip('"') or None,
        )

    def copy_object(
        self,
        *,
        source: ObjectLocation,
        destination: ObjectLocation,
        content_type: str,
        checksum_sha256: str,
    ) -> None:
        self._validate_location(source)
        self._validate_location(destination)
        try:
            self._get_client().copy_object(
                Bucket=destination.bucket,
                Key=destination.key,
                CopySource={"Bucket": source.bucket, "Key": source.key},
                ContentType=content_type,
                MetadataDirective="REPLACE",
                Metadata={"privexa-sha256": checksum_sha256},
                ChecksumAlgorithm="SHA256",
            )
        except (BotoCoreError, ClientError) as error:
            raise ObjectStorageOperationError("OBJECT_STORAGE_COPY_FAILED") from error

    def delete_object(self, *, location: ObjectLocation) -> None:
        self._validate_location(location)
        try:
            self._get_client().delete_object(Bucket=location.bucket, Key=location.key)
        except (BotoCoreError, ClientError) as error:
            raise ObjectStorageOperationError("OBJECT_STORAGE_DELETE_FAILED") from error
