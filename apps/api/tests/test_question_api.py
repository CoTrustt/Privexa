from __future__ import annotations

import io
import json
import logging
from contextlib import contextmanager
from datetime import datetime
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from fixtures.authorization import MultiIdentityStytchGateway
from fixtures.tenant_foundation import (
    ACME_HEALTHCARE_ID,
    APOLLO_FINANCE_ID,
    NORTHSTAR_RETAIL_ID,
)
from pydantic import SecretStr
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from privexa_api.config import Settings
from privexa_api.db.session import build_session_factory
from privexa_api.domain.telemetry import LOGGER as DOMAIN_LOGGER
from privexa_api.main import create_app
from privexa_api.questions import service as question_service
from privexa_api.questions.models import Question

ORIGIN = "http://localhost:3000"


def _build_client(app_engine: Engine) -> TestClient:
    app = create_app(
        settings=Settings(
            APP_DATABASE_URL="postgresql+psycopg://unused",
            STYTCH_PROJECT_ID="project-test-privexa",
            STYTCH_SECRET=SecretStr("secret-test-privexa"),
            PRIVEXA_ENVIRONMENT="test",
            PRIVEXA_WEB_ORIGIN=ORIGIN,
            AI_GATEWAY_ENABLED=False,
            AI_PROVIDER_MODE="disabled",
        ),
        stytch_gateway=MultiIdentityStytchGateway(),
        session_factory=build_session_factory(app_engine),
    )
    return TestClient(app)


def _activate(client: TestClient, client_id: UUID) -> None:
    response = client.put(
        f"/v1/application-context/active-client/{client_id}",
        headers={"Origin": ORIGIN},
    )
    assert response.status_code == 200, response.text


def _post(client: TestClient, path: str, *, json_body: dict[str, object]):
    return client.post(path, json=json_body, headers={"Origin": ORIGIN})


def _patch(client: TestClient, path: str, *, json_body: dict[str, object]):
    return client.patch(path, json=json_body, headers={"Origin": ORIGIN})


def _create_question(client: TestClient, client_id: UUID = APOLLO_FINANCE_ID):
    return _post(
        client,
        f"/v1/clients/{client_id}/questions",
        json_body={
            "title": "  क्या धारा 8(7) लागू होती है?  ",
            "question_text": (
                "क्या DPDP Act, 2023 की धारा 8(7) लागू होती है?\nReference: https://www.meity.gov.in/"
            ),
            "context": "Client term: ‘Applicant Pool’\nRetention proposed: 24 months.",
        },
    )


def test_question_exit_flow_preserves_content_lifecycle_and_events(
    tenant_data,
    app_engine: Engine,
) -> None:
    client = _build_client(app_engine)
    client.cookies.set("stytch_session", "alice-token")
    _activate(client, APOLLO_FINANCE_ID)
    output = io.StringIO()
    handler = logging.StreamHandler(output)
    DOMAIN_LOGGER.addHandler(handler)

    try:
        created = _create_question(client)
        question_id = created.json()["id"]
        retrieved = client.get(f"/v1/clients/{APOLLO_FINANCE_ID}/questions/{question_id}")
        updated = _patch(
            client,
            f"/v1/clients/{APOLLO_FINANCE_ID}/questions/{question_id}",
            json_body={
                "expected_version": 1,
                "context": "Updated factual context — unchanged by AI.",
            },
        )
        resolved = _post(
            client,
            f"/v1/clients/{APOLLO_FINANCE_ID}/questions/{question_id}/resolve",
            json_body={"expected_version": 2},
        )
        closed = _post(
            client,
            f"/v1/clients/{APOLLO_FINANCE_ID}/questions/{question_id}/close",
            json_body={"expected_version": 3},
        )
        reopened = _post(
            client,
            f"/v1/clients/{APOLLO_FINANCE_ID}/questions/{question_id}/reopen",
            json_body={"expected_version": 4},
        )
    finally:
        DOMAIN_LOGGER.removeHandler(handler)

    assert created.status_code == 201
    assert created.headers["location"].endswith(f"/questions/{question_id}")
    assert created.headers["cache-control"] == "private, no-store"
    assert created.json() == {
        "id": question_id,
        "client_id": str(APOLLO_FINANCE_ID),
        "title": "  क्या धारा 8(7) लागू होती है?  ",
        "question_text": (
            "क्या DPDP Act, 2023 की धारा 8(7) लागू होती है?\nReference: https://www.meity.gov.in/"
        ),
        "context": "Client term: ‘Applicant Pool’\nRetention proposed: 24 months.",
        "status": "OPEN",
        "version": 1,
        "created_by_membership_id": str(tenant_data.alice_membership.id),
        "updated_by_membership_id": str(tenant_data.alice_membership.id),
        "created_at": created.json()["created_at"],
        "updated_at": created.json()["updated_at"],
    }
    assert datetime.fromisoformat(created.json()["created_at"]).utcoffset() is not None
    assert datetime.fromisoformat(created.json()["updated_at"]).utcoffset() is not None
    assert retrieved.status_code == 200
    assert retrieved.headers["cache-control"] == "private, no-store"
    assert retrieved.json() == created.json()
    assert updated.json()["version"] == 2
    assert updated.json()["updated_by_membership_id"] == str(tenant_data.alice_membership.id)
    assert resolved.json()["status"] == "RESOLVED"
    assert closed.json()["status"] == "CLOSED"
    assert reopened.json()["status"] == "OPEN"
    assert reopened.json()["version"] == 5

    events = [
        json.loads(line)
        for line in output.getvalue().splitlines()
        if '"event": "domain.event_committed"' in line
    ]
    assert [event["event_type"] for event in events] == [
        "question.created",
        "question.updated",
        "question.resolved",
        "question.closed",
        "question.reopened",
    ]
    assert all(
        event["actor_membership_id"] == str(tenant_data.alice_membership.id) for event in events
    )
    assert "क्या DPDP" not in output.getvalue()
    assert "Updated factual context" not in output.getvalue()


@pytest.mark.security
@pytest.mark.tenant_isolation
def test_cross_client_and_cross_firm_question_read_write_and_lifecycle_are_denied(
    tenant_data,
    app_engine: Engine,
) -> None:
    client = _build_client(app_engine)
    client.cookies.set("stytch_session", "alice-token")
    _activate(client, APOLLO_FINANCE_ID)
    created = _create_question(client)
    question_id = created.json()["id"]

    client.cookies.set("stytch_session", "rahul-token")
    _activate(client, ACME_HEALTHCARE_ID)
    same_firm_read = client.get(f"/v1/clients/{ACME_HEALTHCARE_ID}/questions/{question_id}")
    same_firm_list = client.get(f"/v1/clients/{ACME_HEALTHCARE_ID}/questions")
    same_firm_write = _patch(
        client,
        f"/v1/clients/{ACME_HEALTHCARE_ID}/questions/{question_id}",
        json_body={"expected_version": 1, "title": "Compromised"},
    )
    same_firm_lifecycle = _post(
        client,
        f"/v1/clients/{ACME_HEALTHCARE_ID}/questions/{question_id}/resolve",
        json_body={"expected_version": 1},
    )
    same_firm_close = _post(
        client,
        f"/v1/clients/{ACME_HEALTHCARE_ID}/questions/{question_id}/close",
        json_body={"expected_version": 1},
    )
    same_firm_reopen = _post(
        client,
        f"/v1/clients/{ACME_HEALTHCARE_ID}/questions/{question_id}/reopen",
        json_body={"expected_version": 1},
    )
    nonexistent = client.get(f"/v1/clients/{ACME_HEALTHCARE_ID}/questions/{uuid4()}")

    client.cookies.set("stytch_session", "bob-token")
    _activate(client, NORTHSTAR_RETAIL_ID)
    cross_firm_read = client.get(f"/v1/clients/{NORTHSTAR_RETAIL_ID}/questions/{question_id}")
    cross_firm_list = client.get(f"/v1/clients/{NORTHSTAR_RETAIL_ID}/questions")
    cross_firm_write = _patch(
        client,
        f"/v1/clients/{NORTHSTAR_RETAIL_ID}/questions/{question_id}",
        json_body={"expected_version": 1, "title": "Compromised"},
    )
    cross_firm_lifecycle = _post(
        client,
        f"/v1/clients/{NORTHSTAR_RETAIL_ID}/questions/{question_id}/resolve",
        json_body={"expected_version": 1},
    )

    for response in (
        same_firm_read,
        same_firm_write,
        same_firm_lifecycle,
        same_firm_close,
        same_firm_reopen,
        cross_firm_read,
        cross_firm_write,
        cross_firm_lifecycle,
    ):
        assert response.status_code == 404
        assert response.json()["code"] == "RESOURCE_NOT_FOUND"
        assert response.headers["cache-control"] == "no-store"

    assert same_firm_list.json()["items"] == []
    assert cross_firm_list.json()["items"] == []
    comparable_fields = {"title", "status", "code", "detail"}
    assert {key: same_firm_read.json()[key] for key in comparable_fields} == {
        key: nonexistent.json()[key] for key in comparable_fields
    }

    client.cookies.set("stytch_session", "alice-token")
    _activate(client, APOLLO_FINANCE_ID)
    unchanged = client.get(f"/v1/clients/{APOLLO_FINANCE_ID}/questions/{question_id}")
    assert unchanged.json()["title"] == "  क्या धारा 8(7) लागू होती है?  "
    assert unchanged.json()["status"] == "OPEN"
    assert unchanged.json()["version"] == 1


def test_invalid_transitions_noops_content_lock_and_stale_updates(
    tenant_data,
    app_engine: Engine,
) -> None:
    client = _build_client(app_engine)
    client.cookies.set("stytch_session", "alice-token")
    _activate(client, APOLLO_FINANCE_ID)
    output = io.StringIO()
    handler = logging.StreamHandler(output)
    DOMAIN_LOGGER.addHandler(handler)
    try:
        created = _create_question(client)
        question_id = created.json()["id"]
        already_open = _post(
            client,
            f"/v1/clients/{APOLLO_FINANCE_ID}/questions/{question_id}/reopen",
            json_body={"expected_version": 1},
        )
        invalid_close = _post(
            client,
            f"/v1/clients/{APOLLO_FINANCE_ID}/questions/{question_id}/close",
            json_body={"expected_version": 1},
        )
        resolved = _post(
            client,
            f"/v1/clients/{APOLLO_FINANCE_ID}/questions/{question_id}/resolve",
            json_body={"expected_version": 1},
        )
        repeated = _post(
            client,
            f"/v1/clients/{APOLLO_FINANCE_ID}/questions/{question_id}/resolve",
            json_body={"expected_version": 2},
        )
        content_locked = _patch(
            client,
            f"/v1/clients/{APOLLO_FINANCE_ID}/questions/{question_id}",
            json_body={"expected_version": 2, "title": "Changed after resolution"},
        )
        stale = _post(
            client,
            f"/v1/clients/{APOLLO_FINANCE_ID}/questions/{question_id}/reopen",
            json_body={"expected_version": 1},
        )
        reopened_from_resolved = _post(
            client,
            f"/v1/clients/{APOLLO_FINANCE_ID}/questions/{question_id}/reopen",
            json_body={"expected_version": 2},
        )
        resolved_again = _post(
            client,
            f"/v1/clients/{APOLLO_FINANCE_ID}/questions/{question_id}/resolve",
            json_body={"expected_version": 3},
        )
        closed = _post(
            client,
            f"/v1/clients/{APOLLO_FINANCE_ID}/questions/{question_id}/close",
            json_body={"expected_version": 4},
        )
        repeated_close = _post(
            client,
            f"/v1/clients/{APOLLO_FINANCE_ID}/questions/{question_id}/close",
            json_body={"expected_version": 5},
        )
        invalid_resolve = _post(
            client,
            f"/v1/clients/{APOLLO_FINANCE_ID}/questions/{question_id}/resolve",
            json_body={"expected_version": 5},
        )
    finally:
        DOMAIN_LOGGER.removeHandler(handler)

    assert already_open.status_code == 200
    assert already_open.json()["version"] == 1
    assert invalid_close.status_code == 409
    assert invalid_close.json()["code"] == "LIFECYCLE_CONFLICT"
    assert resolved.json()["version"] == 2
    assert repeated.status_code == 200
    assert repeated.json()["version"] == 2
    assert content_locked.status_code == 409
    assert content_locked.json()["code"] == "LIFECYCLE_CONFLICT"
    assert stale.status_code == 409
    assert stale.json()["code"] == "VERSION_CONFLICT"
    assert reopened_from_resolved.json()["status"] == "OPEN"
    assert reopened_from_resolved.json()["version"] == 3
    assert resolved_again.json()["version"] == 4
    assert closed.json()["version"] == 5
    assert repeated_close.status_code == 200
    assert repeated_close.json()["version"] == 5
    assert invalid_resolve.status_code == 409
    assert invalid_resolve.json()["code"] == "LIFECYCLE_CONFLICT"

    committed_events = [
        json.loads(line)["event_type"]
        for line in output.getvalue().splitlines()
        if '"event": "domain.event_committed"' in line
    ]
    assert committed_events == [
        "question.created",
        "question.resolved",
        "question.reopened",
        "question.resolved",
        "question.closed",
    ]


@pytest.mark.security
def test_mass_assignment_validation_and_read_only_permissions(
    tenant_data,
    app_engine: Engine,
) -> None:
    client = _build_client(app_engine)
    client.cookies.set("stytch_session", "alice-token")
    _activate(client, ACME_HEALTHCARE_ID)
    protected_fields: dict[str, object] = {
        "id": str(uuid4()),
        "firm_id": str(tenant_data.firm_b.id),
        "client_id": str(APOLLO_FINANCE_ID),
        "client_workspace_id": str(APOLLO_FINANCE_ID),
        "created_by": str(tenant_data.bob.id),
        "updated_by": str(tenant_data.bob.id),
        "created_by_membership_id": str(tenant_data.bob_membership.id),
        "updated_by_membership_id": str(tenant_data.bob_membership.id),
        "created_at": "2025-01-01T00:00:00Z",
        "updated_at": "2025-01-01T00:00:00Z",
        "status": "CLOSED",
        "version": 99,
    }
    for field, value in protected_fields.items():
        forged = _post(
            client,
            f"/v1/clients/{ACME_HEALTHCARE_ID}/questions",
            json_body={"title": "Valid", "question_text": "Valid question?", field: value},
        )
        assert forged.status_code == 422
        assert forged.json()["code"] == "REQUEST_VALIDATION_FAILED"

    created = _create_question(client, ACME_HEALTHCARE_ID)
    question_id = created.json()["id"]
    for field, value in protected_fields.items():
        forged_update = _patch(
            client,
            f"/v1/clients/{ACME_HEALTHCARE_ID}/questions/{question_id}",
            json_body={"expected_version": 1, "title": "Valid", field: value},
        )
        assert forged_update.status_code == 422
        assert forged_update.json()["code"] == "REQUEST_VALIDATION_FAILED"

    client.cookies.set("stytch_session", "mark-token")
    _activate(client, ACME_HEALTHCARE_ID)
    read = client.get(f"/v1/clients/{ACME_HEALTHCARE_ID}/questions/{question_id}")
    denied_create = _post(
        client,
        f"/v1/clients/{ACME_HEALTHCARE_ID}/questions",
        json_body={"title": "No", "question_text": "Not permitted"},
    )
    denied_update = _patch(
        client,
        f"/v1/clients/{ACME_HEALTHCARE_ID}/questions/{question_id}",
        json_body={"expected_version": 1, "title": "No"},
    )

    assert read.status_code == 200
    assert denied_create.status_code == denied_update.status_code == 403
    assert denied_create.json()["code"] == denied_update.json()["code"] == "FORBIDDEN"


def test_list_is_bounded_deterministic_filtered_and_paginated(
    tenant_data,
    app_engine: Engine,
) -> None:
    client = _build_client(app_engine)
    client.cookies.set("stytch_session", "alice-token")
    _activate(client, APOLLO_FINANCE_ID)
    created_ids: list[str] = []
    for index in range(55):
        response = _post(
            client,
            f"/v1/clients/{APOLLO_FINANCE_ID}/questions",
            json_body={"title": f"Question {index}", "question_text": f"Text {index}?"},
        )
        created_ids.append(response.json()["id"])
    resolved = _post(
        client,
        f"/v1/clients/{APOLLO_FINANCE_ID}/questions/{created_ids[0]}/resolve",
        json_body={"expected_version": 1},
    )
    assert resolved.status_code == 200

    default_page = client.get(f"/v1/clients/{APOLLO_FINANCE_ID}/questions")
    first = client.get(f"/v1/clients/{APOLLO_FINANCE_ID}/questions?limit=50&offset=0")
    first_repeat = client.get(f"/v1/clients/{APOLLO_FINANCE_ID}/questions?limit=50&offset=0")
    second = client.get(f"/v1/clients/{APOLLO_FINANCE_ID}/questions?limit=50&offset=50")
    filtered = client.get(f"/v1/clients/{APOLLO_FINANCE_ID}/questions?status=RESOLVED")
    invalid_limit = client.get(f"/v1/clients/{APOLLO_FINANCE_ID}/questions?limit=101")
    injection_filter = client.get(
        f"/v1/clients/{APOLLO_FINANCE_ID}/questions?status=OPEN%27%3BDELETE%20FROM%20questions"
    )

    assert default_page.status_code == first.status_code == second.status_code == 200
    assert default_page.json() == first.json()
    assert default_page.headers["cache-control"] == "private, no-store"
    assert len(first.json()["items"]) == 50
    assert first.json()["page"] == {"limit": 50, "offset": 0, "has_more": True}
    assert first_repeat.json() == first.json()
    assert len(second.json()["items"]) == 5
    assert second.json()["page"]["has_more"] is False
    assert {item["id"] for item in first.json()["items"]}.isdisjoint(
        {item["id"] for item in second.json()["items"]}
    )
    assert [item["id"] for item in filtered.json()["items"]] == [created_ids[0]]
    assert invalid_limit.status_code == 422
    assert injection_filter.status_code == 422


def test_question_request_boundaries_authentication_and_safe_errors(
    tenant_data,
    app_engine: Engine,
) -> None:
    client = _build_client(app_engine)
    unauthenticated = client.get(f"/v1/clients/{APOLLO_FINANCE_ID}/questions")
    assert unauthenticated.status_code == 401
    assert unauthenticated.headers["cache-control"] == "no-store"

    client.cookies.set("stytch_session", "expired-token")
    expired = client.get(f"/v1/clients/{APOLLO_FINANCE_ID}/questions")
    assert expired.status_code == 401

    client.cookies.set("stytch_session", "alice-token")
    _activate(client, APOLLO_FINANCE_ID)
    valid_payload = {"title": "T", "question_text": "Q"}
    minimal = _post(
        client,
        f"/v1/clients/{APOLLO_FINANCE_ID}/questions",
        json_body=valid_payload,
    )
    assert minimal.status_code == 201
    assert minimal.json()["context"] is None

    maximum = _post(
        client,
        f"/v1/clients/{APOLLO_FINANCE_ID}/questions",
        json_body={
            "title": "शी" + "x" * 253,
            "question_text": "Q" * 20_000,
            "context": "C" * 50_000,
        },
    )
    assert maximum.status_code == 201
    assert len(maximum.json()["title"]) == 255
    assert len(maximum.json()["question_text"]) == 20_000
    assert len(maximum.json()["context"]) == 50_000

    invalid_payloads = [
        {"question_text": "Q"},
        {"title": "", "question_text": "Q"},
        {"title": " \t\n", "question_text": "Q"},
        {"title": "T" * 256, "question_text": "Q"},
        {"title": "T"},
        {"title": "T", "question_text": ""},
        {"title": "T", "question_text": " \t\n"},
        {"title": "T", "question_text": "Q" * 20_001},
        {"title": "T", "question_text": "Q", "context": ""},
        {"title": "T", "question_text": "Q", "context": " \t\n"},
        {"title": "T", "question_text": "Q", "context": "C" * 50_001},
        {"title": "T", "question_text": "Q", "context": 7},
        {"title": "T", "question_text": "Q", "unknown": "secret-field-canary"},
    ]
    for payload in invalid_payloads:
        invalid = _post(
            client,
            f"/v1/clients/{APOLLO_FINANCE_ID}/questions",
            json_body=payload,
        )
        assert invalid.status_code == 422
        assert invalid.json()["code"] == "REQUEST_VALIDATION_FAILED"
        assert "secret-field-canary" not in invalid.text

    malformed_json = client.post(
        f"/v1/clients/{APOLLO_FINANCE_ID}/questions",
        content=b'{"title": "unterminated',
        headers={"Content-Type": "application/json", "Origin": ORIGIN},
    )
    malformed_client = client.get("/v1/clients/not-a-uuid/questions")
    malformed_question = client.get(f"/v1/clients/{APOLLO_FINANCE_ID}/questions/not-a-uuid")
    nonexistent_workspace = _post(
        client,
        f"/v1/clients/{uuid4()}/questions",
        json_body=valid_payload,
    )
    nonexistent_question = client.get(f"/v1/clients/{APOLLO_FINANCE_ID}/questions/{uuid4()}")
    unsupported_delete = client.delete(
        f"/v1/clients/{APOLLO_FINANCE_ID}/questions/{minimal.json()['id']}",
        headers={"Origin": ORIGIN},
    )

    for invalid in (malformed_json, malformed_client, malformed_question):
        assert invalid.status_code == 422
        assert invalid.json()["code"] == "REQUEST_VALIDATION_FAILED"
    assert nonexistent_workspace.status_code == 404
    assert nonexistent_question.status_code == 404
    assert nonexistent_workspace.json()["code"] == "RESOURCE_NOT_FOUND"
    assert nonexistent_question.json()["code"] == "RESOURCE_NOT_FOUND"
    assert unsupported_delete.status_code == 405
    for response in (
        malformed_json,
        malformed_client,
        malformed_question,
        nonexistent_workspace,
        nonexistent_question,
    ):
        assert not any(
            forbidden in response.text.lower()
            for forbidden in ("sql", "questions_scoped", "traceback", "postgres")
        )


def test_question_optimistic_concurrency_preserves_winning_update(
    tenant_data,
    app_engine: Engine,
) -> None:
    client = _build_client(app_engine)
    client.cookies.set("stytch_session", "alice-token")
    _activate(client, APOLLO_FINANCE_ID)
    created = _create_question(client)
    question_id = created.json()["id"]

    first_reader = client.get(f"/v1/clients/{APOLLO_FINANCE_ID}/questions/{question_id}")
    second_reader = client.get(f"/v1/clients/{APOLLO_FINANCE_ID}/questions/{question_id}")
    assert first_reader.json()["version"] == second_reader.json()["version"] == 1

    winner = _patch(
        client,
        f"/v1/clients/{APOLLO_FINANCE_ID}/questions/{question_id}",
        json_body={"expected_version": 1, "title": "Winning professional wording"},
    )
    stale = _patch(
        client,
        f"/v1/clients/{APOLLO_FINANCE_ID}/questions/{question_id}",
        json_body={"expected_version": 1, "title": "Silent overwrite attempt"},
    )
    final = client.get(f"/v1/clients/{APOLLO_FINANCE_ID}/questions/{question_id}")

    assert winner.status_code == 200
    assert winner.json()["version"] == 2
    assert stale.status_code == 409
    assert stale.json()["code"] == "VERSION_CONFLICT"
    assert final.json()["title"] == "Winning professional wording"
    assert final.json()["version"] == 2


def test_question_updates_each_mutable_field_and_derives_updater_provenance(
    tenant_data,
    app_engine: Engine,
) -> None:
    client = _build_client(app_engine)
    client.cookies.set("stytch_session", "alice-token")
    _activate(client, APOLLO_FINANCE_ID)
    created = _create_question(client)
    question_id = created.json()["id"]

    client.cookies.set("stytch_session", "anita-token")
    _activate(client, APOLLO_FINANCE_ID)
    title_update = _patch(
        client,
        f"/v1/clients/{APOLLO_FINANCE_ID}/questions/{question_id}",
        json_body={"expected_version": 1, "title": "Updated title"},
    )
    text_update = _patch(
        client,
        f"/v1/clients/{APOLLO_FINANCE_ID}/questions/{question_id}",
        json_body={"expected_version": 2, "question_text": "Updated exact text — § 8(7)."},
    )
    clear_context = _patch(
        client,
        f"/v1/clients/{APOLLO_FINANCE_ID}/questions/{question_id}",
        json_body={"expected_version": 3, "context": None},
    )
    repeated_clear = _patch(
        client,
        f"/v1/clients/{APOLLO_FINANCE_ID}/questions/{question_id}",
        json_body={"expected_version": 4, "context": None},
    )
    empty_update = _patch(
        client,
        f"/v1/clients/{APOLLO_FINANCE_ID}/questions/{question_id}",
        json_body={"expected_version": 4},
    )

    assert title_update.status_code == text_update.status_code == clear_context.status_code == 200
    assert title_update.json()["version"] == 2
    assert text_update.json()["version"] == 3
    assert clear_context.json()["version"] == 4
    assert clear_context.json()["title"] == "Updated title"
    assert clear_context.json()["question_text"] == "Updated exact text — § 8(7)."
    assert clear_context.json()["context"] is None
    assert clear_context.json()["created_by_membership_id"] == str(tenant_data.alice_membership.id)
    assert clear_context.json()["updated_by_membership_id"] == str(tenant_data.anita_membership.id)
    assert datetime.fromisoformat(clear_context.json()["updated_at"]) >= datetime.fromisoformat(
        created.json()["updated_at"]
    )
    assert repeated_clear.status_code == 200
    assert repeated_clear.json()["version"] == 4
    assert empty_update.status_code == 422


def test_question_create_rolls_back_when_event_recording_fails(
    tenant_data,
    app_engine: Engine,
    owner_engine: Engine,
    monkeypatch,
) -> None:
    client = _build_client(app_engine)
    client.cookies.set("stytch_session", "alice-token")
    _activate(client, APOLLO_FINANCE_ID)
    output = io.StringIO()
    handler = logging.StreamHandler(output)
    DOMAIN_LOGGER.addHandler(handler)

    def fail_event_recording(*args, **kwargs) -> None:
        raise RuntimeError("synthetic event failure")

    monkeypatch.setattr(question_service, "record_domain_event", fail_event_recording)
    try:
        with pytest.raises(RuntimeError, match="synthetic event failure"):
            _post(
                client,
                f"/v1/clients/{APOLLO_FINANCE_ID}/questions",
                json_body={"title": "Rollback canary", "question_text": "Must not persist"},
            )
    finally:
        DOMAIN_LOGGER.removeHandler(handler)

    with Session(owner_engine) as session:
        persisted = session.scalar(select(Question).where(Question.title == "Rollback canary"))
    assert persisted is None
    assert "domain.event_committed" not in output.getvalue()


def test_question_spans_are_operation_specific_and_content_free(
    tenant_data,
    app_engine: Engine,
    monkeypatch,
) -> None:
    captured: list[tuple[str, dict[str, object]]] = []

    @contextmanager
    def capture_span(name: str, *, attributes: dict[str, object]):
        captured.append((name, attributes))
        yield

    monkeypatch.setattr(question_service, "domain_span", capture_span)
    client = _build_client(app_engine)
    client.cookies.set("stytch_session", "alice-token")
    _activate(client, APOLLO_FINANCE_ID)
    canary = "telemetry-must-not-contain-professional-question-content"
    created = _post(
        client,
        f"/v1/clients/{APOLLO_FINANCE_ID}/questions",
        json_body={"title": canary, "question_text": canary, "context": canary},
    )
    question_id = created.json()["id"]
    client.get(f"/v1/clients/{APOLLO_FINANCE_ID}/questions/{question_id}")
    client.get(f"/v1/clients/{APOLLO_FINANCE_ID}/questions")
    _patch(
        client,
        f"/v1/clients/{APOLLO_FINANCE_ID}/questions/{question_id}",
        json_body={"expected_version": 1, "context": f"updated-{canary}"},
    )
    _post(
        client,
        f"/v1/clients/{APOLLO_FINANCE_ID}/questions/{question_id}/resolve",
        json_body={"expected_version": 2},
    )

    assert [name for name, _ in captured] == [
        "domain.question.create",
        "domain.question.get",
        "domain.question.list",
        "domain.question.update",
        "domain.question.resolve",
    ]
    serialized = json.dumps(captured, default=str)
    assert canary not in serialized
    assert all(
        set(attributes)
        <= {
            "domain.object_type",
            "domain.operation",
            "request.id",
            "trace.id",
            "tenant.firm_id",
            "tenant.client_id",
        }
        for _, attributes in captured
    )


def test_question_openapi_contract_has_no_unapproved_fields(
    tenant_data,
    app_engine: Engine,
) -> None:
    client = _build_client(app_engine)
    document = client.get("/openapi.json").json()
    question_paths = {
        path: set(operations)
        for path, operations in document["paths"].items()
        if "/questions" in path
    }
    assert question_paths == {
        "/v1/clients/{client_id}/questions": {"get", "post"},
        "/v1/clients/{client_id}/questions/{question_id}": {"get", "patch"},
        "/v1/clients/{client_id}/questions/{question_id}/resolve": {"post"},
        "/v1/clients/{client_id}/questions/{question_id}/close": {"post"},
        "/v1/clients/{client_id}/questions/{question_id}/reopen": {"post"},
    }

    schemas = document["components"]["schemas"]
    assert set(schemas["CreateQuestionRequest"]["properties"]) == {
        "title",
        "question_text",
        "context",
    }
    assert schemas["CreateQuestionRequest"]["additionalProperties"] is False
    assert set(schemas["UpdateQuestionRequest"]["properties"]) == {
        "expected_version",
        "title",
        "question_text",
        "context",
    }
    assert schemas["UpdateQuestionRequest"]["additionalProperties"] is False
    response_fields = set(schemas["QuestionResponse"]["properties"])
    assert response_fields == {
        "id",
        "client_id",
        "title",
        "question_text",
        "context",
        "status",
        "version",
        "created_by_membership_id",
        "updated_by_membership_id",
        "created_at",
        "updated_at",
    }
    assert not response_fields & {
        "firm_id",
        "priority",
        "ai_category",
        "ai_summary",
        "ai_answer",
        "ai_confidence",
        "model_name",
        "embedding",
    }
    assert schemas["QuestionStatus"]["enum"] == ["OPEN", "RESOLVED", "CLOSED"]
