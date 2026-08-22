from __future__ import annotations

import json
from itertools import permutations

import pytest
from pydantic import ConfigDict, TypeAdapter, ValidationError

from privexa_api.security.enums import SensitivityLevel
from privexa_api.security.errors import (
    SensitivityFailureReason,
    SensitivityPolicyViolation,
)
from privexa_api.security.sensitivity import DEFAULT_SENSITIVITY, SensitivityPolicy

LEVEL_ADAPTER = TypeAdapter(SensitivityLevel, config=ConfigDict(strict=True))


@pytest.mark.parametrize("level", list(SensitivityLevel))
def test_supported_sensitivity_values_construct_and_round_trip_as_stable_strings(
    level: SensitivityLevel,
) -> None:
    assert SensitivityLevel(level.value) is level
    assert LEVEL_ADAPTER.dump_json(level) == json.dumps(level.value).encode()
    assert LEVEL_ADAPTER.validate_json(json.dumps(level.value)) is level


@pytest.mark.parametrize(
    "invalid_value",
    [
        "UNKNOWN",
        "PRIVATE",
        "SECRET",
        "CONFIDENTIAL",
        "standard",
        "Sensitive",
        "restricted",
        "",
        " ",
        " RESTRICTED ",
        "HIGHLY_RESTRICTED",
        None,
        0,
        1,
        999,
        [],
        {},
    ],
    ids=lambda value: repr(value),
)
def test_unsupported_external_sensitivity_values_fail_validation(invalid_value: object) -> None:
    with pytest.raises(ValidationError):
        LEVEL_ADAPTER.validate_json(json.dumps(invalid_value))


def test_public_policy_ordering_and_equality_are_deterministic() -> None:
    assert (
        SensitivityPolicy.most_restrictive(
            SensitivityLevel.STANDARD,
            SensitivityLevel.SENSITIVE,
        )
        is SensitivityLevel.SENSITIVE
    )
    assert (
        SensitivityPolicy.most_restrictive(
            SensitivityLevel.SENSITIVE,
            SensitivityLevel.RESTRICTED,
        )
        is SensitivityLevel.RESTRICTED
    )
    assert (
        SensitivityPolicy.most_restrictive(
            SensitivityLevel.STANDARD,
            SensitivityLevel.RESTRICTED,
        )
        is SensitivityLevel.RESTRICTED
    )

    for level in SensitivityLevel:
        assert SensitivityPolicy.most_restrictive(level, level) is level
    assert len(set(SensitivityLevel)) == 3


@pytest.mark.parametrize(
    ("current", "requested", "expected"),
    [
        (SensitivityLevel.STANDARD, SensitivityLevel.STANDARD, SensitivityLevel.STANDARD),
        (SensitivityLevel.STANDARD, SensitivityLevel.SENSITIVE, SensitivityLevel.SENSITIVE),
        (SensitivityLevel.STANDARD, SensitivityLevel.RESTRICTED, SensitivityLevel.RESTRICTED),
        (SensitivityLevel.SENSITIVE, SensitivityLevel.STANDARD, None),
        (SensitivityLevel.SENSITIVE, SensitivityLevel.SENSITIVE, SensitivityLevel.SENSITIVE),
        (SensitivityLevel.SENSITIVE, SensitivityLevel.RESTRICTED, SensitivityLevel.RESTRICTED),
        (SensitivityLevel.RESTRICTED, SensitivityLevel.STANDARD, None),
        (SensitivityLevel.RESTRICTED, SensitivityLevel.SENSITIVE, None),
        (SensitivityLevel.RESTRICTED, SensitivityLevel.RESTRICTED, SensitivityLevel.RESTRICTED),
    ],
)
def test_complete_automatic_transition_matrix(
    current: SensitivityLevel,
    requested: SensitivityLevel,
    expected: SensitivityLevel | None,
) -> None:
    original = current
    if expected is None:
        with pytest.raises(SensitivityPolicyViolation) as captured:
            SensitivityPolicy.escalate_to(current, requested)
        assert captured.value.reason == SensitivityFailureReason.AUTOMATIC_DOWNGRADE_FORBIDDEN
        assert captured.value.current is current
        assert captured.value.requested is requested
        assert current is original
        return

    assert SensitivityPolicy.escalate_to(current, requested) is expected
    assert current is original


@pytest.mark.parametrize(
    ("levels", "expected"),
    [
        ([SensitivityLevel.STANDARD], SensitivityLevel.STANDARD),
        ([SensitivityLevel.SENSITIVE], SensitivityLevel.SENSITIVE),
        ([SensitivityLevel.RESTRICTED], SensitivityLevel.RESTRICTED),
        (
            [SensitivityLevel.STANDARD, SensitivityLevel.STANDARD],
            SensitivityLevel.STANDARD,
        ),
        (
            [SensitivityLevel.STANDARD, SensitivityLevel.SENSITIVE],
            SensitivityLevel.SENSITIVE,
        ),
        (
            [SensitivityLevel.STANDARD, SensitivityLevel.RESTRICTED],
            SensitivityLevel.RESTRICTED,
        ),
        (
            [SensitivityLevel.SENSITIVE, SensitivityLevel.SENSITIVE],
            SensitivityLevel.SENSITIVE,
        ),
        (
            [SensitivityLevel.SENSITIVE, SensitivityLevel.RESTRICTED],
            SensitivityLevel.RESTRICTED,
        ),
        (
            [SensitivityLevel.RESTRICTED, SensitivityLevel.RESTRICTED],
            SensitivityLevel.RESTRICTED,
        ),
        (
            [
                SensitivityLevel.STANDARD,
                SensitivityLevel.STANDARD,
                SensitivityLevel.RESTRICTED,
                SensitivityLevel.STANDARD,
            ],
            SensitivityLevel.RESTRICTED,
        ),
    ],
)
def test_most_restrictive_resolution_handles_singletons_pairs_and_duplicates(
    levels: list[SensitivityLevel],
    expected: SensitivityLevel,
) -> None:
    assert SensitivityPolicy.most_restrictive(*levels) is expected


def test_most_restrictive_resolution_is_order_independent() -> None:
    levels = (
        SensitivityLevel.STANDARD,
        SensitivityLevel.SENSITIVE,
        SensitivityLevel.RESTRICTED,
    )

    for ordered_levels in permutations(levels):
        assert SensitivityPolicy.most_restrictive(*ordered_levels) is SensitivityLevel.RESTRICTED


@pytest.mark.parametrize("declared", list(SensitivityLevel))
def test_new_information_retains_each_valid_explicit_classification(
    declared: SensitivityLevel,
) -> None:
    assert SensitivityPolicy.classify_new(declared=declared) is declared


def test_new_information_defaults_only_when_no_classification_input_exists() -> None:
    assert SensitivityPolicy.classify_new() is DEFAULT_SENSITIVITY
    assert (
        SensitivityPolicy.classify_new(inherited=[SensitivityLevel.SENSITIVE])
        is SensitivityLevel.SENSITIVE
    )


@pytest.mark.parametrize(
    ("declared", "inherited", "expected"),
    [
        (SensitivityLevel.STANDARD, SensitivityLevel.STANDARD, SensitivityLevel.STANDARD),
        (SensitivityLevel.SENSITIVE, SensitivityLevel.STANDARD, SensitivityLevel.SENSITIVE),
        (SensitivityLevel.RESTRICTED, SensitivityLevel.STANDARD, SensitivityLevel.RESTRICTED),
        (SensitivityLevel.SENSITIVE, SensitivityLevel.SENSITIVE, SensitivityLevel.SENSITIVE),
        (SensitivityLevel.RESTRICTED, SensitivityLevel.SENSITIVE, SensitivityLevel.RESTRICTED),
        (SensitivityLevel.RESTRICTED, SensitivityLevel.RESTRICTED, SensitivityLevel.RESTRICTED),
    ],
)
def test_new_information_accepts_equal_or_stricter_declared_sensitivity(
    declared: SensitivityLevel,
    inherited: SensitivityLevel,
    expected: SensitivityLevel,
) -> None:
    assert SensitivityPolicy.classify_new(declared=declared, inherited=[inherited]) is expected


@pytest.mark.parametrize(
    ("declared", "inherited"),
    [
        (SensitivityLevel.STANDARD, SensitivityLevel.SENSITIVE),
        (SensitivityLevel.STANDARD, SensitivityLevel.RESTRICTED),
        (SensitivityLevel.SENSITIVE, SensitivityLevel.RESTRICTED),
    ],
)
def test_client_declared_sensitivity_cannot_weaken_inherited_policy(
    declared: SensitivityLevel,
    inherited: SensitivityLevel,
) -> None:
    with pytest.raises(SensitivityPolicyViolation) as captured:
        SensitivityPolicy.classify_new(declared=declared, inherited=[inherited])

    assert captured.value.reason == SensitivityFailureReason.AUTOMATIC_DOWNGRADE_FORBIDDEN


@pytest.mark.parametrize("source", list(SensitivityLevel))
def test_single_source_derived_content_retains_source_sensitivity(
    source: SensitivityLevel,
) -> None:
    assert SensitivityPolicy.classify_derived(sources=[source]) is source


def test_multi_source_ai_style_derivation_uses_the_most_restrictive_source() -> None:
    assert (
        SensitivityPolicy.classify_derived(
            sources=[
                SensitivityLevel.STANDARD,
                SensitivityLevel.SENSITIVE,
                SensitivityLevel.RESTRICTED,
            ]
        )
        is SensitivityLevel.RESTRICTED
    )


def test_derived_content_may_be_explicitly_escalated_above_its_source_floor() -> None:
    assert (
        SensitivityPolicy.classify_derived(
            sources=[SensitivityLevel.STANDARD],
            declared=SensitivityLevel.RESTRICTED,
        )
        is SensitivityLevel.RESTRICTED
    )


@pytest.mark.parametrize(
    ("source", "declared"),
    [
        (SensitivityLevel.SENSITIVE, SensitivityLevel.STANDARD),
        (SensitivityLevel.RESTRICTED, SensitivityLevel.SENSITIVE),
        (SensitivityLevel.RESTRICTED, SensitivityLevel.STANDARD),
    ],
)
def test_summarisation_request_cannot_lower_source_sensitivity(
    source: SensitivityLevel,
    declared: SensitivityLevel,
) -> None:
    with pytest.raises(SensitivityPolicyViolation) as captured:
        SensitivityPolicy.classify_derived(sources=[source], declared=declared)

    assert captured.value.reason == SensitivityFailureReason.AUTOMATIC_DOWNGRADE_FORBIDDEN


def test_mixed_inheritance_and_sources_use_the_highest_applicable_restriction() -> None:
    with pytest.raises(SensitivityPolicyViolation) as captured:
        SensitivityPolicy.classify_derived(
            sources=[SensitivityLevel.RESTRICTED],
            inherited=[SensitivityLevel.SENSITIVE, SensitivityLevel.STANDARD],
            declared=SensitivityLevel.STANDARD,
        )

    assert captured.value.current is SensitivityLevel.RESTRICTED
    assert captured.value.reason == SensitivityFailureReason.AUTOMATIC_DOWNGRADE_FORBIDDEN


def test_derived_from_derived_content_does_not_decay_over_generations() -> None:
    first_generation = SensitivityPolicy.classify_derived(sources=[SensitivityLevel.RESTRICTED])
    second_generation = SensitivityPolicy.classify_derived(sources=[first_generation])

    assert first_generation is SensitivityLevel.RESTRICTED
    assert second_generation is SensitivityLevel.RESTRICTED


def test_blocked_downgrade_remains_blocked_when_retried() -> None:
    for _ in range(2):
        with pytest.raises(SensitivityPolicyViolation) as captured:
            SensitivityPolicy.escalate_to(
                SensitivityLevel.RESTRICTED,
                SensitivityLevel.STANDARD,
            )
        assert captured.value.reason == SensitivityFailureReason.AUTOMATIC_DOWNGRADE_FORBIDDEN


def test_empty_or_invalid_security_inputs_fail_closed() -> None:
    with pytest.raises(SensitivityPolicyViolation) as missing:
        SensitivityPolicy.most_restrictive()
    assert missing.value.reason == SensitivityFailureReason.MISSING_LEVEL

    with pytest.raises(SensitivityPolicyViolation) as empty_sources:
        SensitivityPolicy.classify_derived(sources=[])
    assert empty_sources.value.reason == SensitivityFailureReason.EMPTY_DERIVATION_SOURCES

    with pytest.raises(SensitivityPolicyViolation) as invalid:
        SensitivityPolicy.most_restrictive("SECRET")  # type: ignore[arg-type]
    assert invalid.value.reason == SensitivityFailureReason.INVALID_LEVEL

    with pytest.raises(SensitivityPolicyViolation) as null:
        SensitivityPolicy.most_restrictive(None)  # type: ignore[arg-type]
    assert null.value.reason == SensitivityFailureReason.MISSING_LEVEL
