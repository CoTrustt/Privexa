from __future__ import annotations

import io
import json
import logging
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from fixtures.authorization import MultiIdentityStytchGateway
from fixtures.tenant_foundation import (
    ACME_HEALTHCARE_ID,
    APOLLO_FINANCE_ID,
    NORTHSTAR_RETAIL_ID,
)
from pydantic import SecretStr
from sqlalchemy import Engine

from privexa_api.config import Settings
from privexa_api.db.session import build_session_factory
from privexa_api.domain.telemetry import LOGGER as DOMAIN_LOGGER
from privexa_api.main import create_app

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
    assert created.json()["status"] == "OPEN"
    assert created.json()["version"] == 1
    assert retrieved.status_code == 200
    assert retrieved.json()["title"] == "  क्या धारा 8(7) लागू होती है?  "
    assert retrieved.json()["question_text"].endswith("https://www.meity.gov.in/")
    assert updated.json()["version"] == 2
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

    _activate(client, ACME_HEALTHCARE_ID)
    same_firm_read = client.get(f"/v1/clients/{ACME_HEALTHCARE_ID}/questions/{question_id}")
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

    client.cookies.set("stytch_session", "bob-token")
    _activate(client, NORTHSTAR_RETAIL_ID)
    cross_firm_read = client.get(f"/v1/clients/{NORTHSTAR_RETAIL_ID}/questions/{question_id}")
    cross_firm_write = _patch(
        client,
        f"/v1/clients/{NORTHSTAR_RETAIL_ID}/questions/{question_id}",
        json_body={"expected_version": 1, "title": "Compromised"},
    )

    for response in (
        same_firm_read,
        same_firm_write,
        same_firm_lifecycle,
        cross_firm_read,
        cross_firm_write,
    ):
        assert response.status_code == 404
        assert response.json()["code"] == "RESOURCE_NOT_FOUND"

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
    created = _create_question(client)
    question_id = created.json()["id"]

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

    assert invalid_close.status_code == 409
    assert invalid_close.json()["code"] == "LIFECYCLE_CONFLICT"
    assert resolved.json()["version"] == 2
    assert repeated.status_code == 200
    assert repeated.json()["version"] == 2
    assert content_locked.status_code == 409
    assert content_locked.json()["code"] == "LIFECYCLE_CONFLICT"
    assert stale.status_code == 409
    assert stale.json()["code"] == "VERSION_CONFLICT"


@pytest.mark.security
def test_mass_assignment_validation_and_read_only_permissions(
    tenant_data,
    app_engine: Engine,
) -> None:
    client = _build_client(app_engine)
    client.cookies.set("stytch_session", "alice-token")
    _activate(client, ACME_HEALTHCARE_ID)
    forged = _post(
        client,
        f"/v1/clients/{ACME_HEALTHCARE_ID}/questions",
        json_body={
            "title": "Valid",
            "question_text": "Valid question?",
            "firm_id": str(tenant_data.firm_b.id),
            "client_id": str(APOLLO_FINANCE_ID),
            "status": "CLOSED",
            "version": 99,
        },
    )
    created = _create_question(client, ACME_HEALTHCARE_ID)
    question_id = created.json()["id"]

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

    assert forged.status_code == 422
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
    for index in range(3):
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

    first = client.get(f"/v1/clients/{APOLLO_FINANCE_ID}/questions?limit=2&offset=0")
    second = client.get(f"/v1/clients/{APOLLO_FINANCE_ID}/questions?limit=2&offset=2")
    filtered = client.get(f"/v1/clients/{APOLLO_FINANCE_ID}/questions?status=RESOLVED")
    invalid_limit = client.get(f"/v1/clients/{APOLLO_FINANCE_ID}/questions?limit=101")

    assert first.status_code == second.status_code == filtered.status_code == 200
    assert len(first.json()["items"]) == 2
    assert first.json()["page"] == {"limit": 2, "offset": 0, "has_more": True}
    assert len(second.json()["items"]) == 1
    assert second.json()["page"]["has_more"] is False
    assert {item["id"] for item in first.json()["items"]}.isdisjoint(
        {item["id"] for item in second.json()["items"]}
    )
    assert [item["id"] for item in filtered.json()["items"]] == [created_ids[0]]
    assert invalid_limit.status_code == 422
