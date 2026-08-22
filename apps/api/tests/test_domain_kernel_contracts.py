from __future__ import annotations

import json
from contextlib import nullcontext
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID

import pytest
from fastapi.exceptions import RequestValidationError
from fixtures.domain_kernel import (
    InvalidIdentityProfessionalProbe,
    InvalidTimestampProfessionalProbe,
    ProfessionalRecordProbe,
)
from fixtures.tenant_foundation import (
    ALICE_ID,
    ALICE_MEMBERSHIP_ID,
    APOLLO_FINANCE_ID,
    FIRM_A_ID,
    FIRM_B_ID,
)
from pydantic import ValidationError
from sqlalchemy.orm.exc import StaleDataError
from starlette.requests import Request

from privexa_api.access_control.context import (
    ClientContext,
    _create_client_authorization_context,
)
from privexa_api.access_control.enums import FirmRole
from privexa_api.access_control.errors import AuthorizationDeniedError
from privexa_api.access_control.permissions import Permission
from privexa_api.api.errors import (
    domain_problem_handler,
    request_validation_problem_handler,
    stale_data_problem_handler,
)
from privexa_api.db.professional import validate_professional_object_model
from privexa_api.domain.errors import (
    DomainLifecycleConflictError,
    DomainProblem,
    DomainProblemKind,
    DomainValidationError,
    DomainVersionConflictError,
    TenantOwnershipMismatchError,
)
from privexa_api.domain.events import DomainEvent, DomainEventCollector
from privexa_api.domain.lifecycle import LifecyclePolicy
from privexa_api.observability import tracing
from privexa_api.security.enums import OriginatingChannel, SensitivityLevel
from privexa_api.security.execution_context import ExecutionContext, issue_execution_context
from privexa_api.security.professional_records import (
    ProfessionalRecordAuthority,
    ProfessionalRecordOperation,
    issue_professional_record_authority,
)

REQUEST_ID = UUID("00000000-0000-4000-8000-000000001101")
TRACE_ID = "1234567890abcdef1234567890abcdef"
RECORD_ID = UUID("00000000-0000-4000-8000-000000001102")


class ProbeState(StrEnum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    COMPLETE = "COMPLETE"


class RecordStub:
    def __init__(
        self,
        *,
        firm_id: UUID = FIRM_A_ID,
        client_id: UUID = APOLLO_FINANCE_ID,
        version: int = 1,
    ) -> None:
        self.firm_id = firm_id
        self.client_id = client_id
        self.version = version


def _issued_context(permission: Permission = Permission.CLIENT_UPDATE) -> ExecutionContext:
    authorization = _create_client_authorization_context(
        client_context=ClientContext(
            user_id=ALICE_ID,
            membership_id=ALICE_MEMBERSHIP_ID,
            firm_id=FIRM_A_ID,
            client_id=APOLLO_FINANCE_ID,
            role=FirmRole.CONSULTANT,
        ),
        permission=permission,
    )
    return issue_execution_context(
        authorization=authorization,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        effective_sensitivity=SensitivityLevel.SENSITIVE,
        originating_channel=OriginatingChannel.WEB,
    )


def _request() -> Request:
    request = Request({"type": "http", "method": "PUT", "path": "/test", "headers": []})
    request.state.request_id = REQUEST_ID
    return request


def test_professional_model_adopts_every_kernel_persistence_contract() -> None:
    validate_professional_object_model(ProfessionalRecordProbe, archivable=True)

    table = ProfessionalRecordProbe.__table__
    assert table.columns["id"].primary_key
    assert table.columns["firm_id"].nullable is False
    assert table.columns["client_id"].nullable is False
    assert table.columns["created_at"].type.timezone is True
    assert table.columns["updated_at"].type.timezone is True
    assert table.columns["version"].server_default is not None


def test_model_validation_rejects_wrong_identity_and_timestamp_contracts() -> None:
    with pytest.raises(RuntimeError, match="UUID primary key"):
        validate_professional_object_model(InvalidIdentityProfessionalProbe)
    with pytest.raises(RuntimeError, match="ORM update timestamp"):
        validate_professional_object_model(InvalidTimestampProfessionalProbe)


def test_authority_derives_ownership_and_actor_fields_from_trusted_context() -> None:
    create_authority = issue_professional_record_authority(
        _issued_context(Permission.FILE_CREATE),
        capability=Permission.FILE_CREATE,
        operation=ProfessionalRecordOperation.CREATE,
    )
    update_authority = issue_professional_record_authority(
        _issued_context(),
        capability=Permission.CLIENT_UPDATE,
        operation=ProfessionalRecordOperation.UPDATE,
    )

    assert create_authority.creation_values() == {
        "firm_id": FIRM_A_ID,
        "client_id": APOLLO_FINANCE_ID,
        "created_by_membership_id": ALICE_MEMBERSHIP_ID,
        "updated_by_membership_id": ALICE_MEMBERSHIP_ID,
    }
    assert update_authority.update_values(RecordStub(), expected_version=1) == {
        "updated_by_membership_id": ALICE_MEMBERSHIP_ID,
    }


def test_untrusted_or_wrongly_authorized_callers_cannot_issue_record_authority() -> None:
    direct_context = ExecutionContext.model_validate(_issued_context().model_dump())
    with pytest.raises(AuthorizationDeniedError):
        issue_professional_record_authority(
            direct_context,
            capability=Permission.CLIENT_UPDATE,
            operation=ProfessionalRecordOperation.UPDATE,
        )

    with pytest.raises(AuthorizationDeniedError):
        issue_professional_record_authority(
            _issued_context(Permission.CLIENT_READ),
            capability=Permission.CLIENT_UPDATE,
            operation=ProfessionalRecordOperation.UPDATE,
        )

    with pytest.raises(AuthorizationDeniedError):
        issue_professional_record_authority(
            _issued_context(Permission.CLIENT_READ),
            capability=Permission.CLIENT_READ,
            operation=ProfessionalRecordOperation.UPDATE,
        )

    with pytest.raises(AuthorizationDeniedError):
        issue_professional_record_authority(
            _issued_context(),
            capability=Permission.CLIENT_UPDATE,
            operation="UPDATE",  # type: ignore[arg-type]
        )

    forged = ProfessionalRecordAuthority(
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        user_id=ALICE_ID,
        membership_id=ALICE_MEMBERSHIP_ID,
        firm_id=FIRM_A_ID,
        client_id=APOLLO_FINANCE_ID,
        originating_channel=OriginatingChannel.WEB,
        capability=Permission.CLIENT_UPDATE,
        operation=ProfessionalRecordOperation.UPDATE,
    )
    with pytest.raises(DomainValidationError, match="INVALID_PROFESSIONAL_AUTHORITY"):
        forged.creation_values()


def test_authority_rejects_cross_tenant_and_stale_records_without_disclosure() -> None:
    authority = issue_professional_record_authority(
        _issued_context(),
        capability=Permission.CLIENT_UPDATE,
        operation=ProfessionalRecordOperation.UPDATE,
    )

    with pytest.raises(TenantOwnershipMismatchError) as tenant_error:
        authority.require_record(RecordStub(firm_id=FIRM_B_ID))
    assert tenant_error.value.code == "RESOURCE_NOT_FOUND"
    assert tenant_error.value.diagnostic_code == "TENANT_OWNERSHIP_MISMATCH"

    with pytest.raises(DomainVersionConflictError):
        authority.require_record(RecordStub(version=2), expected_version=1)


def test_archive_contract_is_opt_in_attributed_and_timezone_safe() -> None:
    authority = issue_professional_record_authority(
        _issued_context(Permission.CLIENT_ARCHIVE),
        capability=Permission.CLIENT_ARCHIVE,
        operation=ProfessionalRecordOperation.ARCHIVE,
    )
    archived_at = datetime(2026, 8, 22, 10, 30, tzinfo=UTC)

    values = authority.archive_values(
        RecordStub(),
        expected_version=1,
        archived_at=archived_at,
    )

    assert values == {
        "updated_by_membership_id": ALICE_MEMBERSHIP_ID,
        "archived_at": archived_at,
        "archived_by_membership_id": ALICE_MEMBERSHIP_ID,
    }


def test_lifecycle_policy_is_aggregate_specific_and_terminal_states_are_enforced() -> None:
    policy = LifecyclePolicy(
        allowed_transitions={
            ProbeState.DRAFT: {ProbeState.ACTIVE},
            ProbeState.ACTIVE: {ProbeState.COMPLETE},
            ProbeState.COMPLETE: set(),
        },
        terminal_states={ProbeState.COMPLETE},
    )

    policy.require(ProbeState.DRAFT, ProbeState.ACTIVE)
    assert policy.is_terminal(ProbeState.COMPLETE)
    with pytest.raises(DomainLifecycleConflictError):
        policy.require(ProbeState.DRAFT, ProbeState.COMPLETE)


def test_domain_events_are_immutable_tenant_scoped_and_json_safe() -> None:
    authority = issue_professional_record_authority(
        _issued_context(),
        capability=Permission.CLIENT_UPDATE,
        operation=ProfessionalRecordOperation.UPDATE,
    )
    event = authority.event(
        event_type="kernel_probe.updated",
        aggregate_type="KernelProbe",
        aggregate_id=RECORD_ID,
        payload={"version": 2, "fields": ["title"]},
    )
    collector = DomainEventCollector()
    collector.record(event)

    assert event.firm_id == FIRM_A_ID
    assert event.client_id == APOLLO_FINANCE_ID
    assert event.actor_membership_id == ALICE_MEMBERSHIP_ID
    assert event.occurred_at.tzinfo is not None
    assert event.event_id.version == 4
    assert DomainEvent.model_validate_json(event.model_dump_json()) == event
    assert collector.pending == (event,)
    assert collector.drain() == (event,)
    assert collector.pending == ()

    with pytest.raises(ValidationError):
        DomainEvent(
            **event.model_dump(exclude={"payload"}),
            payload={"unsafe": object()},
        )

    collector.record(event)
    collector.discard()
    assert collector.pending == ()


def test_authority_cannot_be_reused_for_a_different_mutation_kind() -> None:
    authority = issue_professional_record_authority(
        _issued_context(),
        capability=Permission.CLIENT_UPDATE,
        operation=ProfessionalRecordOperation.UPDATE,
    )

    with pytest.raises(DomainValidationError, match="PROFESSIONAL_AUTHORITY_OPERATION_MISMATCH"):
        authority.creation_values()
    with pytest.raises(DomainValidationError, match="PROFESSIONAL_AUTHORITY_OPERATION_MISMATCH"):
        authority.archive_values(RecordStub(), expected_version=1)


def test_domain_error_codes_must_be_stable_identifiers() -> None:
    with pytest.raises(ValueError, match="stable uppercase identifier"):
        DomainProblem(
            kind=DomainProblemKind.VALIDATION,
            code="customer supplied code",
            title="Invalid",
            detail="Invalid",
        )


@pytest.mark.parametrize(
    ("error", "expected_status", "expected_code"),
    [
        (DomainVersionConflictError(), 409, "VERSION_CONFLICT"),
        (TenantOwnershipMismatchError(), 404, "RESOURCE_NOT_FOUND"),
    ],
)
def test_domain_api_errors_are_stable_and_safe(error, expected_status, expected_code) -> None:
    response = domain_problem_handler(_request(), error)
    body = json.loads(response.body)

    assert response.status_code == expected_status
    assert body["code"] == expected_code
    assert body["request_id"] == str(REQUEST_ID)
    assert "TENANT_OWNERSHIP_MISMATCH" not in response.body.decode()


def test_untranslated_sqlalchemy_stale_write_is_safely_mapped() -> None:
    response = stale_data_problem_handler(_request(), StaleDataError("internal mapper details"))
    body = json.loads(response.body)

    assert response.status_code == 409
    assert body["code"] == "VERSION_CONFLICT"
    assert "mapper" not in response.body.decode()


def test_request_validation_errors_are_stable_and_do_not_echo_invalid_input() -> None:
    canary = "customer-secret-input"
    error = RequestValidationError(
        [
            {
                "type": "missing",
                "loc": ("body", "title"),
                "msg": "Field required",
                "input": {"notes": canary},
            },
            {
                "type": "string_too_long",
                "loc": ("body", "notes"),
                "msg": f"Sensitive validator output: {canary}",
                "input": canary,
            },
            {
                "type": "extra_forbidden",
                "loc": ("body", canary),
                "msg": f"Extra field: {canary}",
                "input": canary,
            },
            {
                "type": "string_too_long",
                "loc": ("body", "metadata", canary),
                "msg": f"Nested key: {canary}",
                "input": canary,
            },
        ]
    )

    response = request_validation_problem_handler(_request(), error)
    body = json.loads(response.body)

    assert response.status_code == 422
    assert body["code"] == "REQUEST_VALIDATION_FAILED"
    assert body["field_errors"] == [
        {"path": "body.title", "code": "REQUIRED", "message": "This field is required."},
        {
            "path": "body.notes",
            "code": "INVALID_VALUE",
            "message": "This field value is not valid.",
        },
        {"path": "body", "code": "EXTRA_FIELD", "message": "This field is not accepted."},
        {
            "path": "body.metadata",
            "code": "INVALID_VALUE",
            "message": "This field value is not valid.",
        },
    ]
    assert canary not in response.body.decode()


def test_domain_spans_drop_non_allowlisted_content_attributes(monkeypatch) -> None:
    canary = "customer-evidence-must-not-enter-telemetry"

    class CapturingTracer:
        def __init__(self) -> None:
            self.attributes = {}

        def start_as_current_span(self, name, **kwargs):
            self.attributes = kwargs["attributes"]
            return nullcontext()

    tracer = CapturingTracer()
    monkeypatch.setattr(tracing, "_DOMAIN_TRACER", tracer)

    with tracing.domain_span(
        "domain.kernel_probe.update",
        attributes={
            "domain.operation": "update",
            "domain.object_type": "KernelProbe",
            "tenant.firm_id": str(FIRM_A_ID),
            "domain.result": canary,
            "professional.content": canary,
        },
    ):
        pass

    assert tracer.attributes == {
        "domain.operation": "update",
        "domain.object_type": "KernelProbe",
        "tenant.firm_id": str(FIRM_A_ID),
    }
    assert canary not in json.dumps(tracer.attributes)
