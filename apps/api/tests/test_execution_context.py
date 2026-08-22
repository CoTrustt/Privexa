from __future__ import annotations

import json
from uuid import UUID

import pytest
from fixtures.tenant_foundation import (
    ALICE_ID,
    ALICE_MEMBERSHIP_ID,
    APOLLO_FINANCE_ID,
    FIRM_A_ID,
)
from pydantic import ValidationError

from privexa_api.access_control.context import (
    ClientContext,
    _create_client_authorization_context,
)
from privexa_api.access_control.enums import FirmRole
from privexa_api.access_control.errors import AuthorizationDeniedError
from privexa_api.access_control.permissions import AuthorizationScope, Permission
from privexa_api.security.enums import OriginatingChannel, SensitivityLevel
from privexa_api.security.errors import SensitivityFailureReason, SensitivityPolicyViolation
from privexa_api.security.execution_context import ExecutionContext, issue_execution_context

pytestmark = [pytest.mark.security, pytest.mark.tenant_isolation]

REQUEST_ID = UUID("00000000-0000-4000-8000-000000000201")
TRACE_ID = "0123456789abcdef0123456789abcdef"


def _valid_context_data() -> dict[str, object]:
    return {
        "request_id": REQUEST_ID,
        "trace_id": TRACE_ID,
        "user_id": ALICE_ID,
        "membership_id": ALICE_MEMBERSHIP_ID,
        "firm_id": FIRM_A_ID,
        "client_id": APOLLO_FINANCE_ID,
        "firm_role": FirmRole.CONSULTANT,
        "authorization_scope": AuthorizationScope.CLIENT,
        "granted_capabilities": frozenset({Permission.CLIENT_READ}),
        "effective_sensitivity": SensitivityLevel.STANDARD,
        "originating_channel": OriginatingChannel.WEB,
    }


def _issued_context(
    *,
    role: FirmRole = FirmRole.CONSULTANT,
    permission: Permission = Permission.CLIENT_READ,
    trace_id: str | None = TRACE_ID,
    effective_sensitivity: SensitivityLevel = SensitivityLevel.STANDARD,
) -> ExecutionContext:
    authorization = _create_client_authorization_context(
        client_context=ClientContext(
            user_id=ALICE_ID,
            membership_id=ALICE_MEMBERSHIP_ID,
            firm_id=FIRM_A_ID,
            client_id=APOLLO_FINANCE_ID,
            role=role,
        ),
        permission=permission,
    )
    return issue_execution_context(
        authorization=authorization,
        request_id=REQUEST_ID,
        trace_id=trace_id,
        effective_sensitivity=effective_sensitivity,
        originating_channel=OriginatingChannel.WEB,
    )


def test_valid_execution_context_has_the_complete_typed_structure() -> None:
    context = ExecutionContext(**_valid_context_data())

    assert context.request_id == REQUEST_ID
    assert context.trace_id == TRACE_ID
    assert context.user_id == ALICE_ID
    assert context.membership_id == ALICE_MEMBERSHIP_ID
    assert context.firm_id == FIRM_A_ID
    assert context.client_id == APOLLO_FINANCE_ID
    assert context.firm_role == FirmRole.CONSULTANT
    assert context.authorization_scope == AuthorizationScope.CLIENT
    assert context.granted_capabilities == frozenset({Permission.CLIENT_READ})
    assert context.effective_sensitivity == SensitivityLevel.STANDARD
    assert context.originating_channel == OriginatingChannel.WEB


@pytest.mark.parametrize("missing_field", sorted(ExecutionContext.model_fields))
def test_every_execution_context_field_is_explicitly_required(missing_field: str) -> None:
    data = _valid_context_data()
    data.pop(missing_field)

    with pytest.raises(ValidationError):
        ExecutionContext(**data)


@pytest.mark.parametrize(
    "field_name",
    ["request_id", "user_id", "membership_id", "firm_id", "client_id"],
)
@pytest.mark.parametrize("invalid_value", ["not-a-uuid", "", object()])
def test_authority_identifiers_require_actual_uuid_values(
    field_name: str,
    invalid_value: object,
) -> None:
    data = _valid_context_data()
    data[field_name] = invalid_value

    with pytest.raises(ValidationError):
        ExecutionContext(**data)


@pytest.mark.parametrize("unknown_field", ["is_super_admin", "override_client_id", "metadata"])
def test_unknown_security_fields_are_rejected(unknown_field: str) -> None:
    data = _valid_context_data()
    data[unknown_field] = True

    with pytest.raises(ValidationError) as captured:
        ExecutionContext(**data)

    assert captured.value.errors()[0]["type"] == "extra_forbidden"


@pytest.mark.parametrize(
    "field_name",
    ["user_id", "firm_id", "client_id", "firm_role", "effective_sensitivity"],
)
def test_execution_authority_fields_are_frozen(field_name: str) -> None:
    context = ExecutionContext(**_valid_context_data())

    with pytest.raises(ValidationError) as captured:
        setattr(context, field_name, UUID("00000000-0000-4000-8000-000000000999"))

    assert captured.value.errors()[0]["type"] == "frozen_instance"


def test_capabilities_are_immutable_and_do_not_accept_mutable_collections() -> None:
    context = ExecutionContext(**_valid_context_data())

    with pytest.raises(AttributeError):
        context.granted_capabilities.add(Permission.CLIENT_UPDATE)  # type: ignore[attr-defined]

    data = _valid_context_data()
    data["granted_capabilities"] = [Permission.CLIENT_READ]
    with pytest.raises(ValidationError):
        ExecutionContext(**data)


@pytest.mark.parametrize(
    "invalid_capability",
    ["SUPER_ADMIN", "IGNORE_SECURITY", "cross_client_everything"],
)
def test_arbitrary_strings_cannot_become_capabilities(invalid_capability: str) -> None:
    data = _valid_context_data()
    data["granted_capabilities"] = frozenset({invalid_capability})

    with pytest.raises(ValidationError):
        ExecutionContext(**data)


def test_context_scope_and_capabilities_must_be_consistent() -> None:
    missing_client = _valid_context_data()
    missing_client["client_id"] = None
    with pytest.raises(ValidationError, match="client-scoped execution requires client_id"):
        ExecutionContext(**missing_client)

    firm_with_client = _valid_context_data()
    firm_with_client["authorization_scope"] = AuthorizationScope.FIRM
    firm_with_client["granted_capabilities"] = frozenset({Permission.FIRM_READ})
    with pytest.raises(ValidationError, match="firm and self execution cannot carry client_id"):
        ExecutionContext(**firm_with_client)

    wrong_scope = _valid_context_data()
    wrong_scope["granted_capabilities"] = frozenset({Permission.FIRM_READ})
    with pytest.raises(ValidationError, match="must match the authorization scope"):
        ExecutionContext(**wrong_scope)


@pytest.mark.parametrize("invalid_trace_id", ["trace-123", "A" * 32, "0" * 32])
def test_trace_id_rejects_invalid_or_non_w3c_values(invalid_trace_id: str) -> None:
    data = _valid_context_data()
    data["trace_id"] = invalid_trace_id

    with pytest.raises(ValidationError):
        ExecutionContext(**data)


def test_absent_trace_is_explicit_and_does_not_block_issuance() -> None:
    context = _issued_context(trace_id=None)

    assert context.trace_id is None
    assert context.has_capability(Permission.CLIENT_READ)


def test_privileged_role_does_not_expand_the_authorized_capability() -> None:
    context = _issued_context(role=FirmRole.FIRM_OWNER)

    assert context.firm_role == FirmRole.FIRM_OWNER
    assert context.granted_capabilities == frozenset({Permission.CLIENT_READ})
    assert not context.has_capability(Permission.CLIENT_UPDATE)
    with pytest.raises(AuthorizationDeniedError):
        context.require_capability(Permission.CLIENT_UPDATE)


def test_direct_or_deserialized_context_is_not_trusted_authority() -> None:
    issued = _issued_context()
    direct = ExecutionContext(**_valid_context_data())
    deserialized = ExecutionContext.model_validate_json(issued.model_dump_json())

    for untrusted in (direct, deserialized):
        assert not untrusted.has_capability(Permission.CLIENT_READ)
        with pytest.raises(AuthorizationDeniedError):
            untrusted.require_capability(Permission.CLIENT_READ)
        with pytest.raises(AuthorizationDeniedError):
            untrusted.with_minimum_sensitivity(SensitivityLevel.RESTRICTED)


def test_model_copy_cannot_expand_authority() -> None:
    context = _issued_context()

    with pytest.raises(TypeError, match="cannot be copied with authority updates"):
        context.model_copy(
            update={
                "granted_capabilities": frozenset(
                    {Permission.CLIENT_READ, Permission.CLIENT_UPDATE}
                )
            }
        )

    with pytest.raises(TypeError, match="cannot be copied with authority updates"):
        context.model_copy(update={"effective_sensitivity": SensitivityLevel.RESTRICTED})


def test_serialization_is_deterministic_and_contains_no_credentials_or_billing_state() -> None:
    context = _issued_context()
    serialized = context.model_dump(mode="json")

    assert serialized["granted_capabilities"] == [Permission.CLIENT_READ.value]
    assert serialized["request_id"] == str(REQUEST_ID)
    assert serialized["originating_channel"] == OriginatingChannel.WEB.value
    assert serialized["effective_sensitivity"] == SensitivityLevel.STANDARD.value
    assert set(ExecutionContext.model_fields).isdisjoint(
        {
            "password",
            "raw_jwt",
            "session_cookie",
            "refresh_token",
            "api_key",
            "database_password",
            "oauth_secret",
            "stripe_customer_id",
            "payment_method",
            "invoice_id",
            "subscription_price_id",
        }
    )


def test_safe_logging_projection_is_an_explicit_minimal_allowlist() -> None:
    context = _issued_context()

    assert context.safe_logging_fields() == {
        "request_id": str(REQUEST_ID),
        "trace_id": TRACE_ID,
        "principal_id": str(ALICE_ID),
        "membership_id": str(ALICE_MEMBERSHIP_ID),
        "firm_id": str(FIRM_A_ID),
        "client_id": str(APOLLO_FINANCE_ID),
        "originating_channel": OriginatingChannel.WEB.value,
    }
    assert "granted_capabilities" not in context.safe_logging_fields()
    assert "firm_role" not in context.safe_logging_fields()
    assert "effective_sensitivity" not in context.safe_logging_fields()


def test_trusted_context_sensitivity_is_monotonic_and_immutable() -> None:
    original = _issued_context()

    sensitive = original.with_minimum_sensitivity(SensitivityLevel.SENSITIVE)
    unchanged = sensitive.with_minimum_sensitivity(SensitivityLevel.STANDARD)
    restricted = unchanged.with_minimum_sensitivity(SensitivityLevel.RESTRICTED)

    assert original.effective_sensitivity == SensitivityLevel.STANDARD
    assert sensitive.effective_sensitivity == SensitivityLevel.SENSITIVE
    assert unchanged is sensitive
    assert restricted.effective_sensitivity == SensitivityLevel.RESTRICTED
    assert restricted.request_id == original.request_id
    assert restricted.granted_capabilities == original.granted_capabilities
    assert restricted.has_capability(Permission.CLIENT_READ)


def test_context_sensitivity_sequence_never_forgets_the_highest_level() -> None:
    initial = _issued_context()

    after_standard = initial.with_minimum_sensitivity(SensitivityLevel.STANDARD)
    after_sensitive = after_standard.with_minimum_sensitivity(SensitivityLevel.SENSITIVE)
    after_later_standard = after_sensitive.with_minimum_sensitivity(SensitivityLevel.STANDARD)
    after_restricted = after_later_standard.with_minimum_sensitivity(SensitivityLevel.RESTRICTED)
    final = after_restricted.with_minimum_sensitivity(SensitivityLevel.STANDARD)

    assert initial.effective_sensitivity is SensitivityLevel.STANDARD
    assert after_standard is initial
    assert after_sensitive.effective_sensitivity is SensitivityLevel.SENSITIVE
    assert after_later_standard is after_sensitive
    assert after_restricted.effective_sensitivity is SensitivityLevel.RESTRICTED
    assert final is after_restricted


@pytest.mark.parametrize(
    "less_restrictive",
    [SensitivityLevel.STANDARD, SensitivityLevel.SENSITIVE],
)
def test_restricted_context_neutralizes_full_and_partial_downgrade_attempts(
    less_restrictive: SensitivityLevel,
) -> None:
    restricted = _issued_context(effective_sensitivity=SensitivityLevel.RESTRICTED)

    result = restricted.with_minimum_sensitivity(less_restrictive)

    assert result is restricted
    assert result.effective_sensitivity is SensitivityLevel.RESTRICTED


@pytest.mark.parametrize("level", list(SensitivityLevel))
def test_context_sensitivity_elevation_is_idempotent(level: SensitivityLevel) -> None:
    context = _issued_context(effective_sensitivity=level)

    assert context.with_minimum_sensitivity(level) is context


def test_sensitivity_derivation_preserves_every_other_context_field() -> None:
    original = _issued_context()
    restricted = original.with_minimum_sensitivity(SensitivityLevel.RESTRICTED)
    original_data = original.model_dump()
    restricted_data = restricted.model_dump()

    assert restricted_data.pop("effective_sensitivity") is SensitivityLevel.RESTRICTED
    assert original_data.pop("effective_sensitivity") is SensitivityLevel.STANDARD
    assert restricted_data == original_data
    assert restricted.granted_capabilities == original.granted_capabilities


def test_restricted_sensitivity_survives_serialization_but_not_as_trusted_authority() -> None:
    restricted = _issued_context(effective_sensitivity=SensitivityLevel.RESTRICTED)

    restored = ExecutionContext.model_validate_json(restricted.model_dump_json())

    assert restored.model_dump(mode="json") == restricted.model_dump(mode="json")
    assert restored.effective_sensitivity is SensitivityLevel.RESTRICTED
    assert not restored.has_capability(Permission.CLIENT_READ)
    with pytest.raises(AuthorizationDeniedError):
        restored.with_minimum_sensitivity(SensitivityLevel.STANDARD)


def test_tampered_serialized_context_cannot_become_trusted_downgraded_authority() -> None:
    restricted = _issued_context(effective_sensitivity=SensitivityLevel.RESTRICTED)
    payload = restricted.model_dump(mode="json")
    payload["effective_sensitivity"] = SensitivityLevel.STANDARD.value

    tampered = ExecutionContext.model_validate_json(json.dumps(payload))

    assert tampered.effective_sensitivity is SensitivityLevel.STANDARD
    assert not tampered.has_capability(Permission.CLIENT_READ)
    with pytest.raises(AuthorizationDeniedError):
        tampered.require_capability(Permission.CLIENT_READ)
    with pytest.raises(AuthorizationDeniedError):
        tampered.with_minimum_sensitivity(SensitivityLevel.RESTRICTED)


@pytest.mark.parametrize(
    "invalid_value",
    [None, "", "standard", "CONFIDENTIAL", "HIGHLY_RESTRICTED", 0, [], {}],
    ids=lambda value: repr(value),
)
def test_context_reconstruction_rejects_invalid_sensitivity_metadata(
    invalid_value: object,
) -> None:
    payload = _issued_context().model_dump(mode="json")
    payload["effective_sensitivity"] = invalid_value

    with pytest.raises(ValidationError):
        ExecutionContext.model_validate_json(json.dumps(payload))


def test_context_elevation_requires_at_least_one_valid_minimum() -> None:
    context = _issued_context()

    with pytest.raises(SensitivityPolicyViolation) as missing:
        context.with_minimum_sensitivity()
    assert missing.value.reason == SensitivityFailureReason.MISSING_LEVEL

    with pytest.raises(SensitivityPolicyViolation) as invalid:
        context.with_minimum_sensitivity("RESTRICTED")  # type: ignore[arg-type]
    assert invalid.value.reason == SensitivityFailureReason.INVALID_LEVEL


def test_effective_sensitivity_rejects_direct_mutation_with_a_valid_level() -> None:
    context = _issued_context()

    with pytest.raises(ValidationError) as captured:
        context.effective_sensitivity = SensitivityLevel.RESTRICTED

    assert captured.value.errors()[0]["type"] == "frozen_instance"
    assert context.effective_sensitivity is SensitivityLevel.STANDARD


def test_untrusted_context_cannot_derive_trusted_sensitivity() -> None:
    context = ExecutionContext(**_valid_context_data())

    with pytest.raises(AuthorizationDeniedError):
        context.with_minimum_sensitivity(SensitivityLevel.RESTRICTED)


def test_context_exposes_no_privilege_administration_api_or_dangerous_default_capabilities() -> (
    None
):
    context = _issued_context()
    forbidden_methods = {
        "grant",
        "elevate",
        "assume_role",
        "add_capability",
        "with_admin",
        "set_sensitivity",
        "update_sensitivity",
        "reclassify",
    }
    dangerous_values = {"APPROVE", "SEND", "DELETE", "CROSS_CLIENT", "CHANGE_AUTHORITY"}

    assert all(not hasattr(context, method_name) for method_name in forbidden_methods)
    assert dangerous_values.isdisjoint({capability.name for capability in Permission})
    assert dangerous_values.isdisjoint(
        {capability.name for capability in context.granted_capabilities}
    )
