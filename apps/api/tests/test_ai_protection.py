from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from types import MappingProxyType
from uuid import UUID

import pytest
from fixtures.ai_gateway import trusted_ai_context
from fixtures.pii import (
    AADHAAR_NEGATIVE_CASES,
    AADHAAR_POSITIVE_CASES,
    GENERIC_NEGATIVE_CASES,
    GENERIC_POSITIVE_CASES,
    PAN_NEGATIVE_CASES,
    PAN_POSITIVE_CASES,
    DetectionCase,
    NegativeDetectionCase,
)
from pydantic import ValidationError

from privexa_api.access_control.errors import AuthorizationProblem
from privexa_api.ai_policy.contracts import (
    BUILD0_AGENT_AUTHORITY_CEILING,
    AIFallbackPolicy,
    AIModelClass,
    AIProtectionProfileId,
    AIProviderClass,
    EffectiveAIPolicy,
    RedactionRequirement,
    ZDRRequirement,
)
from privexa_api.ai_protection.contracts import DetectedEntity, ProtectionAction
from privexa_api.ai_protection.errors import (
    ContentProtectionBlocked,
    PIIDetectionError,
    PIITransformationError,
)
from privexa_api.ai_protection.presidio_adapter import (
    PresidioPIIDetector,
    build_presidio_detector,
)
from privexa_api.ai_protection.profiles import EXTERNAL_MODEL_PII_V1, AIProtectionProfile
from privexa_api.ai_protection.recognizers.aadhaar import is_valid_aadhaar
from privexa_api.ai_protection.service import AIProtectionService
from privexa_api.ai_types import AITaskType
from privexa_api.security.execution_context import ExecutionContext


class StaticDetector:
    def __init__(self, detections: tuple[DetectedEntity, ...]) -> None:
        self._detections = detections

    def detect(self, *args: object, **kwargs: object) -> tuple[DetectedEntity, ...]:
        return self._detections


class FailingDetector:
    def detect(self, *args: object, **kwargs: object) -> tuple[DetectedEntity, ...]:
        raise RuntimeError("detector diagnostic must stay internal")


class WholeContentPersonDetector:
    def detect(self, content: str, **kwargs: object) -> tuple[DetectedEntity, ...]:
        return (DetectedEntity(entity_type="PERSON", start=0, end=len(content), score=0.9),)


class EmptyDetector:
    def detect(self, *args: object, **kwargs: object) -> tuple[DetectedEntity, ...]:
        return ()


class ExplodingIfCalledDetector:
    def detect(self, *args: object, **kwargs: object) -> tuple[DetectedEntity, ...]:
        raise AssertionError("detector must not run for the NONE profile")


@pytest.fixture(scope="module")
def presidio_detector() -> PresidioPIIDetector:
    return build_presidio_detector(model_name="en_core_web_sm")


def _policy(
    *,
    profile: AIProtectionProfileId = AIProtectionProfileId.EXTERNAL_MODEL_PII_V1,
    redaction: RedactionRequirement = RedactionRequirement.REQUIRED,
) -> EffectiveAIPolicy:
    return EffectiveAIPolicy(
        allowed_provider_classes=frozenset({AIProviderClass.ZDR_APPROVED}),
        allowed_model_classes=frozenset({AIModelClass.RESTRICTED_DATA_APPROVED}),
        zdr_requirement=ZDRRequirement.REQUIRED,
        redaction_requirement=redaction,
        protection_profile=profile,
        max_input_tokens=4_096,
        max_output_tokens=1_024,
        max_cost_usd=Decimal("0.20"),
        timeout_seconds=20.0,
        fallback_policy=AIFallbackPolicy.NO_FALLBACK,
        allowed_agent_authorities=BUILD0_AGENT_AUTHORITY_CEILING,
    )


def _entity(content: str, value: str, entity_type: str, occurrence: int = 0) -> DetectedEntity:
    start = -1
    for _ in range(occurrence + 1):
        start = content.index(value, start + 1)
    return DetectedEntity(
        entity_type=entity_type,
        start=start,
        end=start + len(value),
        score=0.9,
        recognizer_name="test",
    )


def _detect_case(
    detector: PresidioPIIDetector,
    case: DetectionCase | NegativeDetectionCase,
) -> tuple[DetectedEntity, ...]:
    return detector.detect(
        case.text,
        entities=tuple(EXTERNAL_MODEL_PII_V1.actions),
        language=EXTERNAL_MODEL_PII_V1.language,
        score_threshold=EXTERNAL_MODEL_PII_V1.score_threshold,
    )


@pytest.mark.parametrize("case", GENERIC_POSITIVE_CASES, ids=lambda case: case.case_id)
def test_configured_presidio_generic_positive_catalogue(
    presidio_detector: PresidioPIIDetector,
    case: DetectionCase,
) -> None:
    detections = _detect_case(presidio_detector, case)

    assert sum(item.entity_type == case.entity_type for item in detections) == case.expected_count


@pytest.mark.parametrize("case", GENERIC_NEGATIVE_CASES, ids=lambda case: case.case_id)
def test_configured_presidio_generic_negative_catalogue(
    presidio_detector: PresidioPIIDetector,
    case: NegativeDetectionCase,
) -> None:
    detected_types = {item.entity_type for item in _detect_case(presidio_detector, case)}

    assert detected_types.isdisjoint(case.forbidden_entity_types)


@pytest.mark.parametrize("case", AADHAAR_POSITIVE_CASES, ids=lambda case: case.case_id)
def test_aadhaar_positive_regression_catalogue(
    presidio_detector: PresidioPIIDetector,
    case: DetectionCase,
) -> None:
    detections = _detect_case(presidio_detector, case)

    assert sum(item.entity_type == case.entity_type for item in detections) == case.expected_count


@pytest.mark.parametrize("case", AADHAAR_NEGATIVE_CASES, ids=lambda case: case.case_id)
def test_aadhaar_negative_regression_catalogue(
    presidio_detector: PresidioPIIDetector,
    case: NegativeDetectionCase,
) -> None:
    detected_types = {item.entity_type for item in _detect_case(presidio_detector, case)}

    assert detected_types.isdisjoint(case.forbidden_entity_types)


@pytest.mark.parametrize("case", PAN_POSITIVE_CASES, ids=lambda case: case.case_id)
def test_pan_positive_regression_catalogue(
    presidio_detector: PresidioPIIDetector,
    case: DetectionCase,
) -> None:
    detections = _detect_case(presidio_detector, case)

    assert sum(item.entity_type == case.entity_type for item in detections) == case.expected_count


@pytest.mark.parametrize("case", PAN_NEGATIVE_CASES, ids=lambda case: case.case_id)
def test_pan_negative_regression_catalogue(
    presidio_detector: PresidioPIIDetector,
    case: NegativeDetectionCase,
) -> None:
    detected_types = {item.entity_type for item in _detect_case(presidio_detector, case)}

    assert detected_types.isdisjoint(case.forbidden_entity_types)


@pytest.mark.parametrize(
    ("entity_type", "positive_cases", "negative_cases", "expected_true_positives"),
    [
        (
            "INDIA_AADHAAR",
            AADHAAR_POSITIVE_CASES,
            AADHAAR_NEGATIVE_CASES,
            sum(case.expected_count for case in AADHAAR_POSITIVE_CASES),
        ),
        (
            "INDIA_PAN",
            PAN_POSITIVE_CASES,
            PAN_NEGATIVE_CASES,
            sum(case.expected_count for case in PAN_POSITIVE_CASES),
        ),
    ],
)
def test_custom_recognizer_quality_gate_on_synthetic_catalogue(
    presidio_detector: PresidioPIIDetector,
    entity_type: str,
    positive_cases: tuple[DetectionCase, ...],
    negative_cases: tuple[NegativeDetectionCase, ...],
    expected_true_positives: int,
) -> None:
    true_positives = 0
    false_positives = 0
    false_negatives = 0
    for case in positive_cases:
        detections = _detect_case(presidio_detector, case)
        actual = sum(item.entity_type == entity_type for item in detections)
        true_positives += min(actual, case.expected_count)
        false_positives += max(0, actual - case.expected_count)
        false_negatives += max(0, case.expected_count - actual)
    for case in negative_cases:
        false_positives += sum(
            item.entity_type == entity_type for item in _detect_case(presidio_detector, case)
        )

    assert true_positives == expected_true_positives
    assert false_positives == 0
    assert false_negatives == 0


def test_request_local_transformation_preserves_referential_consistency() -> None:
    content = "Alice emailed Alice at alice@example.com from 192.168.1.1 using 4111 1111 1111 1111."
    detector = StaticDetector(
        (
            _entity(content, "Alice", "PERSON"),
            _entity(content, "Alice", "PERSON", occurrence=1),
            _entity(content, "alice@example.com", "EMAIL_ADDRESS"),
            _entity(content, "192.168.1.1", "IP_ADDRESS"),
            _entity(content, "4111 1111 1111 1111", "CREDIT_CARD"),
        )
    )
    service = AIProtectionService(detector=detector)

    result = service.protect(
        content=content,
        policy=_policy(),
        context=trusted_ai_context(),
        task=AITaskType.SYNTHETIC_TEXT_SUMMARY,
    )

    assert result.protected_content == (
        "<PERSON_001> emailed <PERSON_001> at <EMAIL_ADDRESS_001> from <IP_ADDRESS> "
        "using *******************."
    )
    assert result.detected_entity_count == 5
    assert "Alice" not in result.protected_content
    assert "alice@example.com" not in result.protected_content


def test_same_and_different_values_use_request_local_namespaced_tokens() -> None:
    content = "Alice Bob Alice alice ALICE Alice"
    detector = StaticDetector(
        (
            _entity(content, "Alice", "PERSON"),
            _entity(content, "Bob", "PERSON"),
            _entity(content, "Alice", "PERSON", occurrence=1),
            _entity(content, "alice", "PERSON"),
            _entity(content, "ALICE", "PERSON"),
            _entity(content, "Alice", "LOCATION", occurrence=2),
        )
    )

    result = AIProtectionService(detector=detector).protect(
        content=content,
        policy=_policy(),
        context=trusted_ai_context(),
        task=AITaskType.SYNTHETIC_TEXT_SUMMARY,
    )

    assert result.protected_content == (
        "<PERSON_001> <PERSON_002> <PERSON_001> <PERSON_001> <PERSON_001> <LOCATION_001>"
    )


def test_mask_replace_and_tokenize_preserve_surrounding_text_and_remove_sources() -> None:
    content = "IP=203.0.113.10\nCARD=4111 1111 1111 1111\nEMAIL=boundary@example.com"
    detections = (
        _entity(content, "203.0.113.10", "IP_ADDRESS"),
        _entity(content, "4111 1111 1111 1111", "CREDIT_CARD"),
        _entity(content, "boundary@example.com", "EMAIL_ADDRESS"),
    )

    result = AIProtectionService(detector=StaticDetector(detections)).protect(
        content=content,
        policy=_policy(),
        context=trusted_ai_context(),
        task=AITaskType.SYNTHETIC_TEXT_SUMMARY,
    )

    assert result.protected_content == (
        "IP=<IP_ADDRESS>\nCARD=*******************\nEMAIL=<EMAIL_ADDRESS_001>"
    )
    assert "203.0.113.10" not in result.protected_content
    assert "4111 1111 1111 1111" not in result.protected_content
    assert "boundary@example.com" not in result.protected_content
    assert {summary.action for summary in result.entity_summaries} == {
        ProtectionAction.MASK,
        ProtectionAction.REPLACE,
        ProtectionAction.TOKENIZE,
    }


def test_none_profile_explicitly_permits_original_content_without_detection() -> None:
    content = "Permitted policy content includes permitted@example.com."
    service = AIProtectionService(detector=ExplodingIfCalledDetector())

    result = service.protect(
        content=content,
        policy=_policy(
            profile=AIProtectionProfileId.NONE,
            redaction=RedactionRequirement.NOT_REQUIRED,
        ),
        context=trusted_ai_context(),
        task=AITaskType.SYNTHETIC_TEXT_SUMMARY,
    )

    assert result.protected_content == content
    assert not result.protection_applied
    assert result.entity_summaries == ()


def test_block_action_stops_protection_operation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    content = "Synthetic PAN ABCPA1234D."
    block_profile = AIProtectionProfile(
        profile_id=AIProtectionProfileId.EXTERNAL_MODEL_PII_V1,
        language="en",
        score_threshold=0.4,
        actions=MappingProxyType({"INDIA_PAN": ProtectionAction.BLOCK}),
        precedence=MappingProxyType({"INDIA_PAN": 100}),
    )
    monkeypatch.setattr(
        "privexa_api.ai_protection.service.resolve_protection_profile",
        lambda profile_id: block_profile,
    )
    service = AIProtectionService(
        detector=StaticDetector((_entity(content, "ABCPA1234D", "INDIA_PAN"),))
    )

    with pytest.raises(ContentProtectionBlocked):
        service.protect(
            content=content,
            policy=_policy(),
            context=trusted_ai_context(),
            task=AITaskType.SYNTHETIC_TEXT_SUMMARY,
        )


def test_overlapping_and_duplicate_detections_apply_only_specific_precedence_winner() -> None:
    content = "2345 6789 0124"
    full_span = DetectedEntity(
        entity_type="INDIA_AADHAAR",
        start=0,
        end=len(content),
        score=1.0,
    )
    phone_overlap = DetectedEntity(
        entity_type="PHONE_NUMBER",
        start=0,
        end=len(content),
        score=1.0,
    )

    result = AIProtectionService(
        detector=StaticDetector((phone_overlap, full_span, full_span))
    ).protect(
        content=content,
        policy=_policy(),
        context=trusted_ai_context(),
        task=AITaskType.SYNTHETIC_TEXT_SUMMARY,
    )

    assert result.protected_content == "<INDIA_AADHAAR_001>"
    assert result.detected_entity_count == 1


def test_transformations_handle_beginning_middle_end_and_adjacent_lines() -> None:
    content = "Alice\nBob middle Alice"
    detector = StaticDetector(
        (
            _entity(content, "Alice", "PERSON"),
            _entity(content, "Bob", "PERSON"),
            _entity(content, "Alice", "PERSON", occurrence=1),
        )
    )

    result = AIProtectionService(detector=detector).protect(
        content=content,
        policy=_policy(),
        context=trusted_ai_context(),
        task=AITaskType.SYNTHETIC_TEXT_SUMMARY,
    )

    assert result.protected_content == "<PERSON_001>\n<PERSON_002> middle <PERSON_001>"


def test_required_profile_with_empty_detection_result_sends_unchanged_content_safely() -> None:
    content = "No configured personal information is present."

    result = AIProtectionService(detector=EmptyDetector()).protect(
        content=content,
        policy=_policy(),
        context=trusted_ai_context(),
        task=AITaskType.SYNTHETIC_TEXT_SUMMARY,
    )

    assert result.protected_content == content
    assert result.protection_applied
    assert result.detected_entity_count == 0


def test_protection_result_serialization_has_no_raw_values_or_token_mapping() -> None:
    content = "Alice alice@example.com"
    result = AIProtectionService(
        detector=StaticDetector(
            (
                _entity(content, "Alice", "PERSON"),
                _entity(content, "alice@example.com", "EMAIL_ADDRESS"),
            )
        )
    ).protect(
        content=content,
        policy=_policy(),
        context=trusted_ai_context(),
        task=AITaskType.SYNTHETIC_TEXT_SUMMARY,
    )

    serialized = result.model_dump_json()
    assert "Alice" not in serialized
    assert "alice@example.com" not in serialized
    assert "token_map" not in serialized
    assert "original" not in serialized


@pytest.mark.parametrize(
    "entity",
    [
        DetectedEntity(entity_type="UNSUPPORTED_ENTITY", start=0, end=5, score=1.0),
        DetectedEntity(entity_type="PERSON", start=-1, end=5, score=1.0),
        DetectedEntity(entity_type="PERSON", start=0, end=99, score=1.0),
        DetectedEntity(entity_type="PERSON", start=2, end=2, score=1.0),
    ],
)
def test_invalid_detector_results_fail_transformation_closed(entity: DetectedEntity) -> None:
    with pytest.raises(PIITransformationError):
        AIProtectionService(detector=StaticDetector((entity,))).protect(
            content="Alice",
            policy=_policy(),
            context=trusted_ai_context(),
            task=AITaskType.SYNTHETIC_TEXT_SUMMARY,
        )


def test_detector_controlled_entity_type_cannot_leak_source_value_in_exception() -> None:
    content = "exception.boundary@example.com"
    malicious_result = DetectedEntity(
        entity_type=content,
        start=0,
        end=len(content),
        score=1.0,
    )

    with pytest.raises(PIITransformationError) as captured:
        AIProtectionService(detector=StaticDetector((malicious_result,))).protect(
            content=content,
            policy=_policy(),
            context=trusted_ai_context(),
            task=AITaskType.SYNTHETIC_TEXT_SUMMARY,
        )

    assert content not in str(captured.value)
    assert captured.value.__cause__ is None


def test_token_state_is_not_shared_between_protection_operations() -> None:
    first = "Alice"
    second = "Bob"
    service = AIProtectionService(detector=WholeContentPersonDetector())

    first_result = service.protect(
        content=first,
        policy=_policy(),
        context=trusted_ai_context(),
        task=AITaskType.SYNTHETIC_TEXT_SUMMARY,
    )
    second_result = service.protect(
        content=second,
        policy=_policy(),
        context=trusted_ai_context(),
        task=AITaskType.SYNTHETIC_TEXT_SUMMARY,
    )

    assert first_result.protected_content == "<PERSON_001>"
    assert second_result.protected_content == "<PERSON_001>"


def test_singleton_service_keeps_token_state_isolated_across_concurrent_requests() -> None:
    service = AIProtectionService(detector=WholeContentPersonDetector())
    values = tuple(f"SyntheticPerson{index}" for index in range(16))

    def protect(value: str) -> str:
        return service.protect(
            content=value,
            policy=_policy(),
            context=trusted_ai_context(),
            task=AITaskType.SYNTHETIC_TEXT_SUMMARY,
        ).protected_content

    with ThreadPoolExecutor(max_workers=8) as executor:
        outputs = tuple(executor.map(protect, values))

    assert outputs == ("<PERSON_001>",) * len(values)


def test_reused_presidio_analyzer_is_concurrency_safe_for_request_local_tokens(
    presidio_detector: PresidioPIIDetector,
) -> None:
    service = AIProtectionService(detector=presidio_detector)
    values = tuple(f"concurrent{index}.boundary@example.com" for index in range(8))
    contexts = tuple(trusted_ai_context() for _ in values)

    def protect(item: tuple[str, ExecutionContext]) -> str:
        value, context = item
        return service.protect(
            content=f"Contact {value}",
            policy=_policy(),
            context=context,
            task=AITaskType.SYNTHETIC_TEXT_SUMMARY,
        ).protected_content

    with ThreadPoolExecutor(max_workers=8) as executor:
        outputs = tuple(executor.map(protect, zip(values, contexts, strict=True)))

    assert outputs == ("Contact <EMAIL_ADDRESS_001>",) * len(values)
    assert all(value not in output for value, output in zip(values, outputs, strict=True))


def test_singleton_service_does_not_share_request_state_between_tenants() -> None:
    service = AIProtectionService(detector=WholeContentPersonDetector())
    tenant_a = trusted_ai_context(
        firm_id=UUID("00000000-0000-4000-8000-000000000301"),
        client_id=UUID("00000000-0000-4000-8000-000000000302"),
    )
    tenant_b = trusted_ai_context(
        firm_id=UUID("00000000-0000-4000-8000-000000000401"),
        client_id=UUID("00000000-0000-4000-8000-000000000402"),
    )

    result_a = service.protect(
        content="Alice",
        policy=_policy(),
        context=tenant_a,
        task=AITaskType.SYNTHETIC_TEXT_SUMMARY,
    )
    result_b = service.protect(
        content="Bob",
        policy=_policy(),
        context=tenant_b,
        task=AITaskType.SYNTHETIC_TEXT_SUMMARY,
    )

    assert result_a.protected_content == "<PERSON_001>"
    assert result_b.protected_content == "<PERSON_001>"


def test_protection_service_rejects_untrusted_execution_context() -> None:
    trusted = trusted_ai_context()
    untrusted = ExecutionContext.model_validate(trusted.model_dump())

    with pytest.raises(AuthorizationProblem):
        AIProtectionService(detector=EmptyDetector()).protect(
            content="synthetic",
            policy=_policy(),
            context=untrusted,
            task=AITaskType.SYNTHETIC_TEXT_SUMMARY,
        )


def test_detector_failure_is_normalized_without_raw_content() -> None:
    content = "sensitive-value@example.com"
    service = AIProtectionService(detector=FailingDetector())

    with pytest.raises(PIIDetectionError) as captured:
        service.protect(
            content=content,
            policy=_policy(),
            context=trusted_ai_context(),
            task=AITaskType.SYNTHETIC_TEXT_SUMMARY,
        )

    assert content not in str(captured.value)
    assert captured.value.__cause__ is None


def test_identical_protection_operations_are_deterministic() -> None:
    content = "Alice and Bob"
    detector = StaticDetector(
        (
            _entity(content, "Alice", "PERSON"),
            _entity(content, "Bob", "PERSON"),
        )
    )
    service = AIProtectionService(detector=detector)

    outputs = {
        service.protect(
            content=content,
            policy=_policy(),
            context=trusted_ai_context(),
            task=AITaskType.SYNTHETIC_TEXT_SUMMARY,
        ).protected_content
        for _ in range(25)
    }

    assert outputs == {"<PERSON_001> and <PERSON_002>"}


def test_invalid_protection_configuration_is_rejected() -> None:
    with pytest.raises(ValueError):
        AIProtectionProfile(
            profile_id=AIProtectionProfileId.EXTERNAL_MODEL_PII_V1,
            language="en",
            score_threshold=1.01,
            actions=MappingProxyType({"PERSON": ProtectionAction.TOKENIZE}),
            precedence=MappingProxyType({"PERSON": 1}),
        )
    with pytest.raises(ValueError):
        AIProtectionProfile(
            profile_id=AIProtectionProfileId.EXTERNAL_MODEL_PII_V1,
            language="en",
            score_threshold=0.4,
            actions=MappingProxyType({"PERSON": ProtectionAction.TOKENIZE}),
            precedence=MappingProxyType({"LOCATION": 1}),
        )
    with pytest.raises(ValidationError):
        _policy(profile=AIProtectionProfileId.NONE)


def test_presidio_initialization_failure_is_normalized_without_download_output(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(PIIDetectionError):
        build_presidio_detector(model_name="missing_privexa_test_model")

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_configured_phone_confidence_threshold_includes_boundary_and_excludes_below(
    presidio_detector: PresidioPIIDetector,
) -> None:
    text = "Call +91 98765 43210"

    at_boundary = presidio_detector.detect(
        text,
        entities=("PHONE_NUMBER",),
        language="en",
        score_threshold=EXTERNAL_MODEL_PII_V1.score_threshold,
    )
    above_boundary = presidio_detector.detect(
        text,
        entities=("PHONE_NUMBER",),
        language="en",
        score_threshold=EXTERNAL_MODEL_PII_V1.score_threshold + 0.01,
    )

    assert len(at_boundary) == 1
    assert at_boundary[0].score == EXTERNAL_MODEL_PII_V1.score_threshold
    assert above_boundary == ()


def test_aadhaar_validator_rejects_invalid_shapes_and_checksums() -> None:
    assert is_valid_aadhaar("2345 6789 0124")
    assert is_valid_aadhaar("234567890124")
    assert not is_valid_aadhaar("1234 5678 9012")
    assert not is_valid_aadhaar("2345 6789 0123")
    assert not is_valid_aadhaar("2222 2222 2222")


def test_presidio_adapter_registers_privexa_india_recognizers(
    presidio_detector: PresidioPIIDetector,
) -> None:
    content = "Aadhaar 2345 6789 0124 and PAN abcpa1234d."

    detections = presidio_detector.detect(
        content,
        entities=tuple(EXTERNAL_MODEL_PII_V1.actions),
        language=EXTERNAL_MODEL_PII_V1.language,
        score_threshold=EXTERNAL_MODEL_PII_V1.score_threshold,
    )

    assert {item.entity_type for item in detections} == {"INDIA_AADHAAR", "INDIA_PAN"}


def test_presidio_adapter_detects_build0_generic_catalogue(
    presidio_detector: PresidioPIIDetector,
) -> None:
    content = (
        "John Smith in Mumbai can be called at +91 98765 43210 or emailed at "
        "john.smith@example.com from 203.0.113.10 using card 4111 1111 1111 1111."
    )

    detections = presidio_detector.detect(
        content,
        entities=tuple(EXTERNAL_MODEL_PII_V1.actions),
        language=EXTERNAL_MODEL_PII_V1.language,
        score_threshold=EXTERNAL_MODEL_PII_V1.score_threshold,
    )

    assert {
        "CREDIT_CARD",
        "EMAIL_ADDRESS",
        "IP_ADDRESS",
        "LOCATION",
        "PERSON",
        "PHONE_NUMBER",
    }.issubset({item.entity_type for item in detections})
