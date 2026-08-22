from __future__ import annotations

import io
import json
import logging
from dataclasses import dataclass
from uuid import UUID

import pytest
from fixtures.tenant_foundation import (
    ALICE_ID,
    ALICE_MEMBERSHIP_ID,
    APOLLO_FINANCE_ID,
    FIRM_A_ID,
)

from privexa_api.access_control.context import (
    ClientContext,
    _create_client_authorization_context,
)
from privexa_api.access_control.enums import FirmRole
from privexa_api.access_control.permissions import Permission
from privexa_api.security.enums import OriginatingChannel, SensitivityLevel
from privexa_api.security.errors import (
    SensitivityFailureReason,
    SensitivityPolicyViolation,
)
from privexa_api.security.execution_context import LOGGER, ExecutionContext, issue_execution_context
from privexa_api.security.sensitivity import SensitivityPolicy

pytestmark = [pytest.mark.security, pytest.mark.tenant_isolation]

REQUEST_ID = UUID("00000000-0000-4000-8000-000000000301")
TRACE_ID = "1123456789abcdef0123456789abcdef"
CONFIDENTIAL_MARKER = "NEVER_LOG_THIS_CLIENT_SECRET_7429"


@dataclass(frozen=True, slots=True)
class ProtectedSource:
    sensitivity: SensitivityLevel
    content: str


def _issued_context(
    sensitivity: SensitivityLevel = SensitivityLevel.STANDARD,
) -> ExecutionContext:
    authorization = _create_client_authorization_context(
        client_context=ClientContext(
            user_id=ALICE_ID,
            membership_id=ALICE_MEMBERSHIP_ID,
            firm_id=FIRM_A_ID,
            client_id=APOLLO_FINANCE_ID,
            role=FirmRole.CONSULTANT,
        ),
        permission=Permission.CLIENT_READ,
    )
    return issue_execution_context(
        authorization=authorization,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        effective_sensitivity=sensitivity,
        originating_channel=OriginatingChannel.WEB,
    )


def test_future_tool_string_output_is_not_trusted_sensitivity_authority() -> None:
    source = ProtectedSource(
        sensitivity=SensitivityLevel.RESTRICTED,
        content=CONFIDENTIAL_MARKER,
    )
    untrusted_tool_output = {"effective_sensitivity": "STANDARD"}

    with pytest.raises(SensitivityPolicyViolation) as raw_value:
        SensitivityPolicy.classify_derived(
            sources=[source.sensitivity],
            declared=untrusted_tool_output["effective_sensitivity"],  # type: ignore[arg-type]
        )
    assert raw_value.value.reason == SensitivityFailureReason.INVALID_LEVEL

    with pytest.raises(SensitivityPolicyViolation) as parsed_value:
        SensitivityPolicy.classify_derived(
            sources=[source.sensitivity],
            declared=SensitivityLevel(untrusted_tool_output["effective_sensitivity"]),
        )
    assert parsed_value.value.reason == SensitivityFailureReason.AUTOMATIC_DOWNGRADE_FORBIDDEN


def test_ai_style_derived_result_elevates_context_before_downstream_processing() -> None:
    context = _issued_context()
    sources = [
        ProtectedSource(SensitivityLevel.STANDARD, "public facts"),
        ProtectedSource(SensitivityLevel.SENSITIVE, "client facts"),
        ProtectedSource(SensitivityLevel.RESTRICTED, CONFIDENTIAL_MARKER),
    ]

    derived_sensitivity = SensitivityPolicy.classify_derived(
        sources=[source.sensitivity for source in sources]
    )
    downstream_context = context.with_minimum_sensitivity(derived_sensitivity)
    after_standard = downstream_context.with_minimum_sensitivity(SensitivityLevel.STANDARD)

    assert derived_sensitivity is SensitivityLevel.RESTRICTED
    assert downstream_context.effective_sensitivity is SensitivityLevel.RESTRICTED
    assert after_standard is downstream_context


@pytest.mark.parametrize(
    ("declared", "inherited", "context_level", "sources", "expected"),
    [
        (
            SensitivityLevel.RESTRICTED,
            [SensitivityLevel.SENSITIVE],
            SensitivityLevel.STANDARD,
            [SensitivityLevel.STANDARD],
            SensitivityLevel.RESTRICTED,
        ),
        (
            SensitivityLevel.SENSITIVE,
            [SensitivityLevel.STANDARD],
            SensitivityLevel.RESTRICTED,
            [SensitivityLevel.STANDARD],
            SensitivityLevel.RESTRICTED,
        ),
        (
            SensitivityLevel.STANDARD,
            [SensitivityLevel.STANDARD],
            SensitivityLevel.STANDARD,
            [SensitivityLevel.STANDARD],
            SensitivityLevel.STANDARD,
        ),
    ],
)
def test_effective_sensitivity_combines_resource_inputs_with_execution_context(
    declared: SensitivityLevel,
    inherited: list[SensitivityLevel],
    context_level: SensitivityLevel,
    sources: list[SensitivityLevel],
    expected: SensitivityLevel,
) -> None:
    resource_level = SensitivityPolicy.classify_derived(
        sources=sources,
        inherited=inherited,
        declared=declared,
    )
    effective_context = _issued_context(context_level).with_minimum_sensitivity(resource_level)

    assert effective_context.effective_sensitivity is expected


def test_context_elevation_log_contains_policy_metadata_but_not_protected_content() -> None:
    source = ProtectedSource(
        sensitivity=SensitivityLevel.RESTRICTED,
        content=CONFIDENTIAL_MARKER,
    )
    output = io.StringIO()
    handler = logging.StreamHandler(output)
    previous_level = LOGGER.level
    previous_disabled = LOGGER.disabled
    LOGGER.disabled = False
    LOGGER.setLevel(logging.INFO)
    LOGGER.addHandler(handler)

    try:
        _issued_context().with_minimum_sensitivity(source.sensitivity)
    finally:
        LOGGER.removeHandler(handler)
        LOGGER.setLevel(previous_level)
        LOGGER.disabled = previous_disabled

    logged = output.getvalue()
    event = json.loads(logged)
    assert event == {
        "client_id": str(APOLLO_FINANCE_ID),
        "effective_sensitivity": SensitivityLevel.RESTRICTED.value,
        "event": "sensitivity.context_elevated",
        "firm_id": str(FIRM_A_ID),
        "membership_id": str(ALICE_MEMBERSHIP_ID),
        "originating_channel": OriginatingChannel.WEB.value,
        "policy_result": "ELEVATE",
        "previous_sensitivity": SensitivityLevel.STANDARD.value,
        "principal_id": str(ALICE_ID),
        "request_id": str(REQUEST_ID),
        "trace_id": TRACE_ID,
    }
    assert CONFIDENTIAL_MARKER not in logged


def test_blocked_downgrade_error_exposes_only_policy_metadata() -> None:
    source = ProtectedSource(
        sensitivity=SensitivityLevel.RESTRICTED,
        content=CONFIDENTIAL_MARKER,
    )

    with pytest.raises(SensitivityPolicyViolation) as captured:
        SensitivityPolicy.classify_derived(
            sources=[source.sensitivity],
            declared=SensitivityLevel.STANDARD,
        )

    error = captured.value
    assert str(error) == SensitivityFailureReason.AUTOMATIC_DOWNGRADE_FORBIDDEN.value
    assert error.current is SensitivityLevel.RESTRICTED
    assert error.requested is SensitivityLevel.STANDARD
    assert CONFIDENTIAL_MARKER not in str(error)
