from enum import StrEnum


class StoredFileStatus(StrEnum):
    PENDING_UPLOAD = "PENDING_UPLOAD"
    AVAILABLE = "AVAILABLE"
    FAILED = "FAILED"
    DELETED = "DELETED"


class StorageProvider(StrEnum):
    S3_COMPATIBLE = "S3_COMPATIBLE"
