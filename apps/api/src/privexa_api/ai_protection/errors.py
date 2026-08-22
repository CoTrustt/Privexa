from __future__ import annotations


class AIProtectionError(Exception):
    """Base error whose message never contains request content or entity values."""


class PIIDetectionError(AIProtectionError):
    def __init__(self) -> None:
        super().__init__("PII detection could not be completed safely")


class PIITransformationError(AIProtectionError):
    def __init__(self, entity_type: str | None = None) -> None:
        del entity_type
        super().__init__("Required PII transformation failed")


class UnsupportedProtectionProfile(AIProtectionError):
    def __init__(self) -> None:
        super().__init__("The selected PII protection profile is not supported")


class ContentProtectionBlocked(AIProtectionError):
    def __init__(self, entity_type: str) -> None:
        super().__init__(f"Policy blocks model execution for detected entity type {entity_type}")
