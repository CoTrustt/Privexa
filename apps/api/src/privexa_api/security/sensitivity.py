from __future__ import annotations

from collections.abc import Iterable

from privexa_api.security.enums import SensitivityLevel
from privexa_api.security.errors import (
    SensitivityFailureReason,
    SensitivityPolicyViolation,
)

DEFAULT_SENSITIVITY = SensitivityLevel.STANDARD


class SensitivityPolicy:
    """Deterministic, provider-neutral rules for information sensitivity."""

    @staticmethod
    def most_restrictive(*levels: SensitivityLevel) -> SensitivityLevel:
        if not levels:
            raise SensitivityPolicyViolation(
                reason=SensitivityFailureReason.MISSING_LEVEL,
            )
        validated = tuple(_require_level(level) for level in levels)
        return max(validated, key=lambda level: level.severity)

    @staticmethod
    def classify_new(
        *,
        declared: SensitivityLevel | None = None,
        inherited: Iterable[SensitivityLevel] = (),
    ) -> SensitivityLevel:
        inherited_levels = tuple(_require_level(level) for level in inherited)
        if declared is None:
            if not inherited_levels:
                return DEFAULT_SENSITIVITY
            return SensitivityPolicy.most_restrictive(*inherited_levels)

        declared_level = _require_level(declared)
        if inherited_levels:
            inherited_floor = SensitivityPolicy.most_restrictive(*inherited_levels)
            _ensure_not_lower(current=inherited_floor, requested=declared_level)
        return SensitivityPolicy.most_restrictive(declared_level, *inherited_levels)

    @staticmethod
    def classify_derived(
        *,
        sources: Iterable[SensitivityLevel],
        declared: SensitivityLevel | None = None,
        inherited: Iterable[SensitivityLevel] = (),
    ) -> SensitivityLevel:
        source_levels = tuple(_require_level(level) for level in sources)
        if not source_levels:
            raise SensitivityPolicyViolation(
                reason=SensitivityFailureReason.EMPTY_DERIVATION_SOURCES,
            )
        inherited_levels = tuple(_require_level(level) for level in inherited)
        source_floor = SensitivityPolicy.most_restrictive(
            *source_levels,
            *inherited_levels,
        )
        if declared is None:
            return source_floor

        declared_level = _require_level(declared)
        _ensure_not_lower(current=source_floor, requested=declared_level)
        return SensitivityPolicy.most_restrictive(source_floor, declared_level)

    @staticmethod
    def escalate_to(
        current: SensitivityLevel,
        requested: SensitivityLevel,
    ) -> SensitivityLevel:
        current_level = _require_level(current)
        requested_level = _require_level(requested)
        _ensure_not_lower(current=current_level, requested=requested_level)
        return requested_level


def _require_level(value: object) -> SensitivityLevel:
    if not isinstance(value, SensitivityLevel):
        raise SensitivityPolicyViolation(
            reason=(
                SensitivityFailureReason.MISSING_LEVEL
                if value is None
                else SensitivityFailureReason.INVALID_LEVEL
            )
        )
    return value


def _ensure_not_lower(
    *,
    current: SensitivityLevel,
    requested: SensitivityLevel,
) -> None:
    if requested.severity < current.severity:
        raise SensitivityPolicyViolation(
            reason=SensitivityFailureReason.AUTOMATIC_DOWNGRADE_FORBIDDEN,
            current=current,
            requested=requested,
        )
