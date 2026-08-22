from __future__ import annotations

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from privexa_api.ai_gateway.models import AIProviderRuntimeControl
from privexa_api.ai_gateway.routing import AIProviderName
from privexa_api.ai_policy.models import AIPolicyRuntimeControl
from privexa_api.ai_types import AITaskType
from privexa_api.api.routes.ai_tasks import router as ai_tasks_router
from privexa_api.operations.ai_controls import (
    inspect_ai_controls,
    set_global_ai,
    set_provider_ai,
    set_task_ai,
)


def test_operator_controls_are_revisioned_and_idempotent(owner_engine: Engine) -> None:
    connection = owner_engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection)
    try:
        global_revision = set_global_ai(session, enabled=True)
        task_revision = set_task_ai(
            session,
            task=AITaskType.PREPARE_WORK_NOTE,
            enabled=False,
        )
        provider_revision = set_provider_ai(
            session,
            provider=AIProviderName.OPENROUTER,
            enabled=False,
        )
        assert set_global_ai(session, enabled=True) == global_revision
        assert (
            set_task_ai(
                session,
                task=AITaskType.PREPARE_WORK_NOTE,
                enabled=False,
            )
            == task_revision
        )
        assert (
            set_provider_ai(
                session,
                provider=AIProviderName.OPENROUTER,
                enabled=False,
            )
            == provider_revision
        )
        current_global = session.scalar(
            select(AIPolicyRuntimeControl).where(
                AIPolicyRuntimeControl.task_id.is_(None),
                AIPolicyRuntimeControl.superseded_at.is_(None),
            )
        )
        current_task = session.scalar(
            select(AIPolicyRuntimeControl).where(
                AIPolicyRuntimeControl.task_id == AITaskType.PREPARE_WORK_NOTE.value,
                AIPolicyRuntimeControl.superseded_at.is_(None),
            )
        )
        current_provider = session.scalar(
            select(AIProviderRuntimeControl).where(
                AIProviderRuntimeControl.provider_id == AIProviderName.OPENROUTER.value,
                AIProviderRuntimeControl.superseded_at.is_(None),
            )
        )
        assert current_global is not None and current_global.enabled is True
        assert current_task is not None and current_task.enabled is False
        assert current_provider is not None and current_provider.enabled is False
        snapshot = inspect_ai_controls(session)
        policy_controls = snapshot["policy_controls"]
        provider_controls = snapshot["provider_controls"]
        assert isinstance(policy_controls, list)
        assert isinstance(provider_controls, list)
        assert all(control["configuration_valid"] is True for control in policy_controls)
        assert all(control["configuration_valid"] is True for control in provider_controls)
        assert "circuits" in snapshot
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.mark.parametrize(
    "provider_id",
    ["openrouter", "OPENROUTER ", "../OPENROUTER", "unknown-provider", "", "null"],
)
def test_provider_identifier_manipulation_is_rejected(provider_id: str) -> None:
    with pytest.raises(ValueError):
        AIProviderName(provider_id)


@pytest.mark.parametrize(
    "task_id",
    [
        "AI.PREPARE_WORK_NOTE",
        "ai.prepare_work_note ",
        "../ai.prepare_work_note",
        "unknown-task",
        "",
        "null",
    ],
)
def test_task_identifier_manipulation_is_rejected(task_id: str) -> None:
    with pytest.raises(ValueError):
        AITaskType(task_id)


def test_runtime_ai_router_exposes_no_control_mutation_endpoint() -> None:
    exposed = {
        (method, route.path)
        for route in ai_tasks_router.routes
        for method in (route.methods or set())
    }

    assert exposed == {
        ("GET", "/ai/tasks/ai.prepare_work_note/capability"),
        ("POST", "/ai/tasks/ai.prepare_work_note/prepare"),
    }
