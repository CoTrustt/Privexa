from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from time import monotonic
from typing import Protocol

from privexa_api.ai_policy.contracts import AIProtectionProfileId, EffectiveAIPolicy
from privexa_api.ai_protection.contracts import (
    DetectedEntity,
    ProtectionAction,
    ProtectionEntitySummary,
    ProtectionResult,
)
from privexa_api.ai_protection.errors import (
    AIProtectionError,
    ContentProtectionBlocked,
    PIIDetectionError,
    PIITransformationError,
)
from privexa_api.ai_protection.profiles import AIProtectionProfile, resolve_protection_profile
from privexa_api.ai_types import AITaskType
from privexa_api.security.execution_context import (
    ExecutionContext,
    require_trusted_execution_context,
)


class PIIDetector(Protocol):
    def detect(
        self,
        content: str,
        *,
        entities: tuple[str, ...],
        language: str,
        score_threshold: float,
    ) -> tuple[DetectedEntity, ...]: ...


class AIProtection(Protocol):
    def protect(
        self,
        *,
        content: str,
        policy: EffectiveAIPolicy,
        context: ExecutionContext,
        task: AITaskType,
    ) -> ProtectionResult: ...


class AIProtectionService:
    """Executes policy-selected protection without retaining request-local values."""

    def __init__(self, *, detector: PIIDetector) -> None:
        self._detector = detector

    def protect(
        self,
        *,
        content: str,
        policy: EffectiveAIPolicy,
        context: ExecutionContext,
        task: AITaskType,
    ) -> ProtectionResult:
        require_trusted_execution_context(context)
        if not isinstance(task, AITaskType):
            raise PIITransformationError
        started = monotonic()
        if policy.protection_profile is AIProtectionProfileId.NONE:
            return ProtectionResult(
                protected_content=content,
                profile_id=AIProtectionProfileId.NONE,
                protection_applied=False,
                duration_ms=_duration_ms(started),
            )

        profile = resolve_protection_profile(policy.protection_profile)
        try:
            detected = self._detector.detect(
                content,
                entities=tuple(profile.actions),
                language=profile.language,
                score_threshold=profile.score_threshold,
            )
        except AIProtectionError:
            raise
        except Exception:
            raise PIIDetectionError from None

        selected = _resolve_overlaps(detected, profile=profile, content_length=len(content))
        try:
            protected, summaries = _transform(content, selected, profile=profile)
        except AIProtectionError:
            raise
        except Exception:
            raise PIITransformationError from None
        return ProtectionResult(
            protected_content=protected,
            profile_id=profile.profile_id,
            protection_applied=True,
            entity_summaries=summaries,
            duration_ms=_duration_ms(started),
        )


def _resolve_overlaps(
    detections: Iterable[DetectedEntity],
    *,
    profile: AIProtectionProfile,
    content_length: int,
) -> tuple[DetectedEntity, ...]:
    valid: list[DetectedEntity] = []
    for entity in detections:
        if entity.entity_type not in profile.actions:
            raise PIITransformationError(entity.entity_type)
        if entity.start < 0 or entity.end > content_length or entity.start >= entity.end:
            raise PIITransformationError(entity.entity_type)
        valid.append(entity)

    ranked = sorted(
        valid,
        key=lambda item: (
            -profile.precedence.get(item.entity_type, 0),
            -(item.end - item.start),
            -item.score,
            item.start,
            item.entity_type,
        ),
    )
    selected: list[DetectedEntity] = []
    for candidate in ranked:
        if any(candidate.start < item.end and item.start < candidate.end for item in selected):
            continue
        selected.append(candidate)
    return tuple(sorted(selected, key=lambda item: (item.start, item.end, item.entity_type)))


def _transform(
    content: str,
    detections: tuple[DetectedEntity, ...],
    *,
    profile: AIProtectionProfile,
) -> tuple[str, tuple[ProtectionEntitySummary, ...]]:
    chunks: list[str] = []
    cursor = 0
    token_map: dict[tuple[str, str], str] = {}
    token_counters: Counter[str] = Counter()
    entity_counts: Counter[tuple[str, ProtectionAction]] = Counter()

    for entity in detections:
        action = profile.actions[entity.entity_type]
        raw_value = content[entity.start : entity.end]
        chunks.append(content[cursor : entity.start])
        chunks.append(
            _replacement(
                entity_type=entity.entity_type,
                raw_value=raw_value,
                action=action,
                token_map=token_map,
                token_counters=token_counters,
            )
        )
        entity_counts[(entity.entity_type, action)] += 1
        cursor = entity.end
    chunks.append(content[cursor:])

    summaries = tuple(
        ProtectionEntitySummary(entity_type=entity_type, count=count, action=action)
        for (entity_type, action), count in sorted(
            entity_counts.items(), key=lambda item: (item[0][0], item[0][1].value)
        )
    )
    return "".join(chunks), summaries


def _replacement(
    *,
    entity_type: str,
    raw_value: str,
    action: ProtectionAction,
    token_map: dict[tuple[str, str], str],
    token_counters: Counter[str],
) -> str:
    if action is ProtectionAction.BLOCK:
        raise ContentProtectionBlocked(entity_type)
    if action is ProtectionAction.REPLACE:
        return f"<{entity_type}>"
    if action is ProtectionAction.MASK:
        return "*" * len(raw_value)
    if action is ProtectionAction.TOKENIZE:
        key = (entity_type, " ".join(raw_value.casefold().split()))
        token = token_map.get(key)
        if token is None:
            token_counters[entity_type] += 1
            token = f"<{entity_type}_{token_counters[entity_type]:03d}>"
            token_map[key] = token
        return token
    raise PIITransformationError(entity_type)


def _duration_ms(started: float) -> int:
    return max(0, round((monotonic() - started) * 1_000))
