from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from fixtures.authorization import MultiIdentityStytchGateway
from fixtures.tenant_foundation import (
    ACME_HEALTHCARE_ID,
    ALICE_MEMBERSHIP_ID,
    APOLLO_FINANCE_ID,
    FIRM_A_ID,
    RESTRICTED_CLIENT_ID,
)
from pydantic import SecretStr
from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session

from privexa_api.ai_gateway.models import AIProviderRuntimeControl
from privexa_api.ai_gateway.providers.deterministic import DeterministicAIProvider
from privexa_api.ai_gateway.routing import AIProviderName
from privexa_api.ai_policy.models import AIPolicyRuntimeControl
from privexa_api.ai_protection.contracts import DetectedEntity
from privexa_api.ai_provenance.models import AIExecution, AIExecutionSource
from privexa_api.config import Settings
from privexa_api.db.session import build_session_factory
from privexa_api.files.enums import StorageProvider, StoredFileStatus
from privexa_api.files.models import StoredFile
from privexa_api.main import create_app
from privexa_api.security.enums import SensitivityLevel
from privexa_api.storage.keys import build_stored_file_keys

APOLLO_SOURCE_FILE_ID = UUID("00000000-0000-4000-8000-000000001301")
ACME_SOURCE_FILE_ID = UUID("00000000-0000-4000-8000-000000001302")


class SyntheticPIIDetector:
    def detect(self, content: str, **_: object) -> tuple[DetectedEntity, ...]:
        values = (
            ("Ananya Sharma", "PERSON"),
            ("ananya.sharma@example.test", "EMAIL_ADDRESS"),
            ("+91 90000 00000", "PHONE_NUMBER"),
        )
        return tuple(
            DetectedEntity(
                entity_type=entity_type,
                start=content.index(value),
                end=content.index(value) + len(value),
                score=0.99,
            )
            for value, entity_type in values
            if value in content
        )


def _available_source_file(*, file_id: UUID, client_id: UUID) -> StoredFile:
    keys = build_stored_file_keys(
        firm_id=FIRM_A_ID,
        client_id=client_id,
        file_id=file_id,
    )
    return StoredFile(
        id=file_id,
        firm_id=FIRM_A_ID,
        client_id=client_id,
        storage_provider=StorageProvider.S3_COMPATIBLE,
        storage_bucket="privexa-test",
        storage_key=keys.storage_key,
        upload_storage_key=keys.upload_key,
        original_filename="authorized-source.pdf",
        mime_type="application/pdf",
        size_bytes=32,
        checksum_sha256="a" * 64,
        status=StoredFileStatus.AVAILABLE,
        sensitivity_level=SensitivityLevel.STANDARD,
        created_by_membership_id=ALICE_MEMBERSHIP_ID,
        upload_expires_at=datetime.now(UTC) + timedelta(minutes=15),
        completed_at=datetime.now(UTC),
    )


def _control_hash(value: dict[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


@contextmanager
def _temporarily_disable_control(
    owner_engine: Engine,
    *,
    target: str,
) -> Iterator[None]:
    with Session(owner_engine) as session, session.begin():
        if target == "task":
            row = session.scalar(
                select(AIPolicyRuntimeControl).where(
                    AIPolicyRuntimeControl.task_id == "ai.prepare_work_note",
                    AIPolicyRuntimeControl.superseded_at.is_(None),
                )
            )
            assert row is not None
            canonical = {
                "task_id": row.task_id,
                "enabled": False,
                "revision": row.revision,
            }
        else:
            row = session.scalar(
                select(AIProviderRuntimeControl).where(
                    AIProviderRuntimeControl.provider_id == AIProviderName.DETERMINISTIC.value,
                    AIProviderRuntimeControl.superseded_at.is_(None),
                )
            )
            assert row is not None
            canonical = {
                "provider_id": row.provider_id,
                "enabled": False,
                "revision": row.revision,
            }
        original_enabled = row.enabled
        original_hash = row.configuration_hash
        control_id = row.id
        row.enabled = False
        row.configuration_hash = _control_hash(canonical)
    try:
        yield
    finally:
        with Session(owner_engine) as session, session.begin():
            model = AIPolicyRuntimeControl if target == "task" else AIProviderRuntimeControl
            restored = session.get(model, control_id)
            assert restored is not None
            restored.enabled = original_enabled
            restored.configuration_hash = original_hash


@pytest.fixture
def ai_runtime_enabled(owner_engine: Engine) -> Iterator[None]:
    with owner_engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE ai_policy_runtime_controls SET enabled = true, "
                "configuration_hash = :hash WHERE task_id IS NULL"
            ),
            {"hash": "ed07c2b808b5d2d1621a55b8869212fe6e7d2f742ceeacf95ccc1e351d1b9bb7"},
        )
    try:
        yield
    finally:
        with owner_engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE ai_policy_runtime_controls SET enabled = false, "
                    "configuration_hash = :hash WHERE task_id IS NULL"
                ),
                {"hash": ("fd5acff4086fd9dd45ea9bf14c08dbd63cffc385af6285c8a278b6c4738cd099")},
            )


def test_active_client_work_note_flow_and_zero_cost_restricted_denial(
    tenant_data,
    ai_runtime_enabled: None,
    app_engine: Engine,
    owner_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with Session(owner_engine) as session, session.begin():
        session.add_all(
            (
                _available_source_file(
                    file_id=APOLLO_SOURCE_FILE_ID,
                    client_id=APOLLO_FINANCE_ID,
                ),
                _available_source_file(
                    file_id=ACME_SOURCE_FILE_ID,
                    client_id=ACME_HEALTHCARE_ID,
                ),
            )
        )
    provider = DeterministicAIProvider()
    monkeypatch.setattr(
        "privexa_api.ai_gateway.factory.DeterministicAIProvider",
        lambda: provider,
    )
    monkeypatch.setattr(
        "privexa_api.ai_gateway.factory.build_presidio_detector",
        lambda **_: SyntheticPIIDetector(),
    )
    app = create_app(
        settings=Settings(
            APP_DATABASE_URL="postgresql+psycopg://unused",
            STYTCH_PROJECT_ID="project-test-privexa",
            STYTCH_SECRET=SecretStr("secret-test-privexa"),
            PRIVEXA_ENVIRONMENT="test",
            PRIVEXA_WEB_ORIGIN="http://localhost:3000",
            AI_GATEWAY_ENABLED=True,
            AI_PROVIDER_MODE="deterministic",
        ),
        stytch_gateway=MultiIdentityStytchGateway(),
        session_factory=build_session_factory(app_engine),
    )
    headers = {"Origin": "http://localhost:3000"}
    note = (
        "Ananya Sharma can be reached at ananya.sharma@example.test or +91 90000 00000. "
        "Supporting evidence remains synthetic."
    )
    with TestClient(app) as client:
        unauthenticated = client.post(
            "/v1/ai/tasks/ai.prepare_work_note/prepare",
            headers=headers,
            json={"note": note},
        )
        assert unauthenticated.status_code == 401
        assert provider.invocation_count == 0

        client.cookies.set("stytch_session", "alice-token")
        assert (
            client.put(
                f"/v1/application-context/active-client/{APOLLO_FINANCE_ID}",
                headers=headers,
            ).status_code
            == 200
        )
        capability = client.get(
            "/v1/ai/tasks/ai.prepare_work_note/capability",
        )
        assert capability.status_code == 200
        assert capability.json() == {
            "task_id": "ai.prepare_work_note",
            "state": "AVAILABLE",
            "available": True,
            "retryable": False,
            "retry_after_seconds": None,
        }
        assert provider.invocation_count == 0
        unknown_task = client.post(
            "/v1/ai/tasks/attacker-controlled/prepare",
            headers=headers,
            json={"note": note},
        )
        assert unknown_task.status_code == 404
        assert provider.invocation_count == 0

        tampered = client.post(
            "/v1/ai/tasks/ai.prepare_work_note/prepare",
            headers=headers,
            json={
                "note": note,
                "task_version": "999",
                "model": "attacker/chosen-model",
                "provider": "openrouter",
                "max_tokens": 100_000,
                "timeout": 99_999,
                "retries": 100,
                "fallback": "all",
                "zdr": False,
                "policy_outcome": "ALLOW",
            },
        )
        assert tampered.status_code == 422
        assert provider.invocation_count == 0

        over_limit = client.post(
            "/v1/ai/tasks/ai.prepare_work_note/prepare",
            headers=headers,
            json={"note": "x" * 5_001},
        )
        assert over_limit.status_code == 422
        assert provider.invocation_count == 0

        prepared = client.post(
            "/v1/ai/tasks/ai.prepare_work_note/prepare",
            headers=headers,
            json={"note": note, "source_file_ids": [str(APOLLO_SOURCE_FILE_ID)]},
        )
        assert prepared.status_code == 200
        assert prepared.json()["status"] == "PREPARED"
        assert prepared.json()["candidate"]["authoritative"] is False
        assert prepared.json()["candidate"]["review_required"] is True
        assert provider.invocation_count == 1

        cross_client_source = client.post(
            "/v1/ai/tasks/ai.prepare_work_note/prepare",
            headers=headers,
            json={"note": note, "source_file_ids": [str(ACME_SOURCE_FILE_ID)]},
        )
        assert cross_client_source.status_code == 200
        assert cross_client_source.json()["status"] == "RESTRICTED"
        assert cross_client_source.json()["problem"]["code"] == "AI_CONTEXT_RESTRICTED"
        assert provider.invocation_count == 1

        assert (
            client.put(
                f"/v1/application-context/active-client/{RESTRICTED_CLIENT_ID}",
                headers=headers,
            ).status_code
            == 200
        )
        restricted = client.post(
            "/v1/ai/tasks/ai.prepare_work_note/prepare",
            headers=headers,
            json={"note": note},
        )
        assert restricted.status_code == 200
        assert restricted.json()["status"] == "RESTRICTED"
        assert restricted.json()["problem"]["code"] == "AI_CONTEXT_RESTRICTED"
        assert provider.invocation_count == 1
        restricted_capability = client.get(
            "/v1/ai/tasks/ai.prepare_work_note/capability",
        )
        assert restricted_capability.status_code == 200
        assert restricted_capability.json()["state"] == "RESTRICTED"
        assert restricted_capability.json()["available"] is False
        assert provider.invocation_count == 1

    with owner_engine.connect() as connection:
        execution = connection.execute(
            text(
                "SELECT provider_attempt_count, cost_amount FROM ai_executions "
                "WHERE id = :execution_id"
            ),
            {"execution_id": restricted.json()["execution_id"]},
        ).one()
    assert execution.provider_attempt_count == 0
    assert execution.cost_amount is None

    with Session(owner_engine) as session:
        prepared_execution = session.get(
            AIExecution,
            UUID(prepared.json()["execution_id"]),
        )
        prepared_sources = session.scalars(
            select(AIExecutionSource).where(
                AIExecutionSource.execution_id == UUID(prepared.json()["execution_id"])
            )
        ).all()
        rejected_execution = session.get(
            AIExecution,
            UUID(cross_client_source.json()["execution_id"]),
        )
        rejected_sources = session.scalars(
            select(AIExecutionSource).where(
                AIExecutionSource.execution_id == UUID(cross_client_source.json()["execution_id"])
            )
        ).all()
    assert prepared_execution is not None
    assert prepared_execution.source_reference_count == 1
    assert [(source.source_type, source.source_id) for source in prepared_sources] == [
        ("stored_file", APOLLO_SOURCE_FILE_ID)
    ]
    assert rejected_execution is not None
    assert rejected_execution.source_reference_count == 0
    assert rejected_execution.provider_attempt_count == 0
    assert rejected_sources == []


def test_direct_work_note_api_cannot_bypass_global_deployment_kill_switch(
    tenant_data,
    app_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = DeterministicAIProvider()
    monkeypatch.setattr(
        "privexa_api.ai_gateway.factory.DeterministicAIProvider",
        lambda: provider,
    )
    app = create_app(
        settings=Settings(
            APP_DATABASE_URL="postgresql+psycopg://unused",
            STYTCH_PROJECT_ID="project-test-privexa",
            STYTCH_SECRET=SecretStr("secret-test-privexa"),
            PRIVEXA_ENVIRONMENT="test",
            PRIVEXA_WEB_ORIGIN="http://localhost:3000",
            AI_GATEWAY_ENABLED=False,
            AI_PROVIDER_MODE="deterministic",
        ),
        stytch_gateway=MultiIdentityStytchGateway(),
        session_factory=build_session_factory(app_engine),
    )
    headers = {"Origin": "http://localhost:3000"}

    with TestClient(app) as client:
        client.cookies.set("stytch_session", "alice-token")
        selected = client.put(
            f"/v1/application-context/active-client/{APOLLO_FINANCE_ID}",
            headers=headers,
        )
        assert selected.status_code == 200

        capability = client.get("/v1/ai/tasks/ai.prepare_work_note/capability")
        blocked = client.post(
            "/v1/ai/tasks/ai.prepare_work_note/prepare",
            headers=headers,
            json={"note": "Manual consultant work remains authoritative."},
        )

    assert capability.status_code == 200
    assert capability.json()["available"] is False
    assert capability.json()["state"] == "UNAVAILABLE"
    assert blocked.status_code == 200
    assert blocked.json()["status"] == "FAILED"
    assert blocked.json()["problem"] == {
        "code": "AI_DISABLED",
        "detail": (
            "Privexa assistance is temporarily unavailable. You can continue working normally."
        ),
        "retryable": False,
        "retry_after_seconds": None,
    }
    assert provider.invocation_count == 0


@pytest.mark.parametrize(
    ("target", "expected_code"),
    [
        ("task", "AI_TASK_UNAVAILABLE"),
        ("provider", "AI_UNAVAILABLE"),
    ],
)
def test_direct_work_note_api_cannot_bypass_task_or_provider_disablement(
    tenant_data,
    ai_runtime_enabled: None,
    app_engine: Engine,
    owner_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
    target: str,
    expected_code: str,
) -> None:
    provider = DeterministicAIProvider()
    monkeypatch.setattr(
        "privexa_api.ai_gateway.factory.DeterministicAIProvider",
        lambda: provider,
    )
    app = create_app(
        settings=Settings(
            APP_DATABASE_URL="postgresql+psycopg://unused",
            STYTCH_PROJECT_ID="project-test-privexa",
            STYTCH_SECRET=SecretStr("secret-test-privexa"),
            PRIVEXA_ENVIRONMENT="test",
            PRIVEXA_WEB_ORIGIN="http://localhost:3000",
            AI_GATEWAY_ENABLED=True,
            AI_PROVIDER_MODE="deterministic",
        ),
        stytch_gateway=MultiIdentityStytchGateway(),
        session_factory=build_session_factory(app_engine),
    )
    headers = {"Origin": "http://localhost:3000"}

    with TestClient(app) as client:
        client.cookies.set("stytch_session", "alice-token")
        selected = client.put(
            f"/v1/application-context/active-client/{APOLLO_FINANCE_ID}",
            headers=headers,
        )
        assert selected.status_code == 200
        with _temporarily_disable_control(owner_engine, target=target):
            blocked = client.post(
                "/v1/ai/tasks/ai.prepare_work_note/prepare",
                headers=headers,
                json={"note": "Manual work remains available."},
            )

    assert blocked.status_code == 200
    assert blocked.json()["status"] == "FAILED"
    assert blocked.json()["problem"]["code"] == expected_code
    assert blocked.json()["problem"]["retryable"] is False
    assert provider.invocation_count == 0
