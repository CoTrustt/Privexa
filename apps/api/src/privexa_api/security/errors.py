from __future__ import annotations

from enum import StrEnum

from privexa_api.security.enums import SensitivityLevel


class SensitivityFailureReason(StrEnum):
    INVALID_LEVEL = "SENSITIVITY_INVALID_LEVEL"
    MISSING_LEVEL = "SENSITIVITY_MISSING_LEVEL"
    EMPTY_DERIVATION_SOURCES = "SENSITIVITY_EMPTY_DERIVATION_SOURCES"
    AUTOMATIC_DOWNGRADE_FORBIDDEN = "SENSITIVITY_AUTOMATIC_DOWNGRADE_FORBIDDEN"


class SensitivityPolicyViolation(Exception):
    """A deterministic sensitivity invariant could not be satisfied safely."""

    def __init__(
        self,
        *,
        reason: SensitivityFailureReason,
        current: SensitivityLevel | None = None,
        requested: SensitivityLevel | None = None,
    ) -> None:
        super().__init__(reason.value)
        self.reason = reason
        self.current = current
        self.requested = requested
