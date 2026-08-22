from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from fixtures.authorization import MultiIdentityStytchGateway
from fixtures.tenant_foundation import APOLLO_FINANCE_ID, RESTRICTED_CLIENT_ID
from pydantic import SecretStr
from sqlalchemy import Engine, text

from privexa_api.config import Settings
from privexa_api.db.session import build_session_factory
from privexa_api.main import create_app

pytestmark = [
    pytest.mark.ai_integration,
    pytest.mark.skipif(
        os.getenv("PRIVEXA_RUN_LIVE_AI") != "1",
        reason="live AI validation requires explicit PRIVEXA_RUN_LIVE_AI=1",
    ),
]


@pytest.fixture
def live_ai_runtime_enabled(owner_engine: Engine) -> Iterator[None]:
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


def test_live_openrouter_work_note_records_structured_usage_and_cost(
    tenant_data,
    live_ai_runtime_enabled: None,
    app_engine: Engine,
    owner_engine: Engine,
) -> None:
    api_key = os.getenv("OPENROUTER_API_KEY")
    model = os.getenv("AI_PREPARE_WORK_NOTE_MODEL")
    if not api_key or not model:
        pytest.skip("live OpenRouter credential and work-note model are not configured")

    app = create_app(
        settings=Settings(
            APP_DATABASE_URL="postgresql+psycopg://unused-development",
            STYTCH_PROJECT_ID="project-test-privexa",
            STYTCH_SECRET=SecretStr("secret-test-privexa"),
            PRIVEXA_ENVIRONMENT="development",
            PRIVEXA_WEB_ORIGIN="http://localhost:3000",
            AI_GATEWAY_ENABLED=True,
            AI_PROVIDER_MODE="openrouter",
            OPENROUTER_API_KEY=SecretStr(api_key),
            AI_PREPARE_WORK_NOTE_MODEL=model,
            AI_APPROVED_OPENROUTER_MODELS=[model],
        ),
        stytch_gateway=MultiIdentityStytchGateway(),
        session_factory=build_session_factory(app_engine),
    )
    headers = {"Origin": "http://localhost:3000"}
    synthetic_note = (
        "Ananya Sharma can be reached at ananya.sharma@example.test or +91 90000 00000. "
        "Prepare a provisional note identifying that supporting evidence still needs review."
    )
    with TestClient(app) as client:
        client.cookies.set("stytch_session", "alice-token")
        assert (
            client.put(
                f"/v1/application-context/active-client/{APOLLO_FINANCE_ID}",
                headers=headers,
            ).status_code
            == 200
        )
        response = client.post(
            "/v1/ai/tasks/ai.prepare_work_note/prepare",
            headers=headers,
            json={"note": synthetic_note},
        )
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
            json={"note": synthetic_note},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "PREPARED"
    assert body["candidate"]["authoritative"] is False
    assert body["candidate"]["review_required"] is True
    assert restricted.status_code == 200
    assert restricted.json()["status"] == "RESTRICTED"
    assert restricted.json()["problem"]["code"] == "AI_CONTEXT_RESTRICTED"

    with owner_engine.connect() as connection:
        execution = connection.execute(
            text(
                "SELECT provider_attempt_count, retry_count, fallback_count, prompt_tokens, "
                "completion_tokens, total_tokens, cost_amount, cost_currency, output_hash "
                "FROM ai_executions WHERE id = :execution_id"
            ),
            {"execution_id": body["execution_id"]},
        ).one()
        restricted_execution = connection.execute(
            text(
                "SELECT provider_attempt_count, cost_amount FROM ai_executions "
                "WHERE id = :execution_id"
            ),
            {"execution_id": restricted.json()["execution_id"]},
        ).one()
    assert execution.provider_attempt_count == 1
    assert execution.retry_count == 0
    assert execution.fallback_count == 0
    assert execution.prompt_tokens is not None
    assert execution.completion_tokens is not None
    assert execution.total_tokens is not None
    assert execution.cost_amount is not None
    assert execution.cost_currency == "USD"
    assert execution.output_hash is not None
    assert restricted_execution.provider_attempt_count == 0
    assert restricted_execution.cost_amount is None
