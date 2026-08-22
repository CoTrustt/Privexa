from __future__ import annotations

import hashlib
import json
from typing import Protocol

from pydantic import ValidationError
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from privexa_api.ai_policy.contracts import (
    AIPolicyConstraints,
    AIPolicyRule,
    AIPolicyRuleReference,
    AIPolicyRuntimeSnapshot,
)
from privexa_api.ai_policy.errors import InvalidAIPolicyConfiguration
from privexa_api.ai_policy.models import AIPolicyOverride, AIPolicyRuntimeControl
from privexa_api.ai_types import AITaskType
from privexa_api.db.tenant_scope import require_matching_execution_context_scope
from privexa_api.security.enums import SensitivityLevel
from privexa_api.security.execution_context import ExecutionContext


class AIPolicySnapshotRepository(Protocol):
    def validate_startup(
        self,
        session: Session,
        *,
        registered_tasks: frozenset[AITaskType],
    ) -> None: ...

    def load(
        self,
        session: Session | None,
        *,
        context: ExecutionContext,
        task: AITaskType,
        sensitivity: SensitivityLevel,
    ) -> AIPolicyRuntimeSnapshot: ...


class DatabaseAIPolicyRepository:
    def validate_startup(
        self,
        session: Session,
        *,
        registered_tasks: frozenset[AITaskType],
    ) -> None:
        controls = session.scalars(
            select(AIPolicyRuntimeControl).where(AIPolicyRuntimeControl.superseded_at.is_(None))
        ).all()
        for control in controls:
            _validate_runtime_control(control)
        global_controls = [control for control in controls if control.task_id is None]
        task_ids = {control.task_id for control in controls if control.task_id is not None}
        if len(global_controls) != 1 or task_ids != {task.value for task in registered_tasks}:
            raise InvalidAIPolicyConfiguration(
                "AI policy requires one current global and registered-task control"
            )

    def load(
        self,
        session: Session | None,
        *,
        context: ExecutionContext,
        task: AITaskType,
        sensitivity: SensitivityLevel,
    ) -> AIPolicyRuntimeSnapshot:
        if session is None:
            raise InvalidAIPolicyConfiguration("tenant-scoped policy lookup requires a Session")
        require_matching_execution_context_scope(session, context)

        controls = session.scalars(
            select(AIPolicyRuntimeControl)
            .where(
                AIPolicyRuntimeControl.superseded_at.is_(None),
                or_(
                    AIPolicyRuntimeControl.task_id.is_(None),
                    AIPolicyRuntimeControl.task_id == task.value,
                ),
            )
            .order_by(AIPolicyRuntimeControl.task_id.asc().nullsfirst())
        ).all()
        for control in controls:
            _validate_runtime_control(control)
        global_controls = [control for control in controls if control.task_id is None]
        task_controls = [control for control in controls if control.task_id == task.value]
        if len(global_controls) > 1 or len(task_controls) > 1:
            raise InvalidAIPolicyConfiguration("multiple current AI policy controls")

        rows = session.scalars(
            select(AIPolicyOverride)
            .where(
                AIPolicyOverride.firm_id == context.firm_id,
                AIPolicyOverride.superseded_at.is_(None),
                or_(
                    AIPolicyOverride.client_id.is_(None),
                    AIPolicyOverride.client_id == context.client_id,
                ),
                or_(AIPolicyOverride.task_id.is_(None), AIPolicyOverride.task_id == task.value),
                or_(
                    AIPolicyOverride.sensitivity.is_(None),
                    AIPolicyOverride.sensitivity == sensitivity.value,
                ),
            )
            .order_by(AIPolicyOverride.client_id.asc().nullsfirst(), AIPolicyOverride.id)
        ).all()

        try:
            overrides = tuple(_override_rule(row) for row in rows)
        except (ValidationError, ValueError) as error:
            raise InvalidAIPolicyConfiguration("invalid tenant AI policy override") from error

        control_references = tuple(
            AIPolicyRuleReference(
                rule_id=(
                    "runtime:global"
                    if control.task_id is None
                    else f"runtime:task:{control.task_id}"
                ),
                revision=control.revision,
                content_hash=control.configuration_hash,
            )
            for control in controls
        )
        return AIPolicyRuntimeSnapshot(
            global_enabled=global_controls[0].enabled if global_controls else None,
            task_enabled=task_controls[0].enabled if task_controls else None,
            control_references=control_references,
            override_rules=overrides,
        )


class StaticAIPolicyRepository:
    """Validated no-cache policy state for unit tests and bounded internal composition."""

    def __init__(
        self,
        *,
        global_enabled: bool = True,
        task_enabled: bool = True,
        override_rules: tuple[AIPolicyRule, ...] = (),
    ) -> None:
        self._snapshot = AIPolicyRuntimeSnapshot(
            global_enabled=global_enabled,
            task_enabled=task_enabled,
            override_rules=override_rules,
        )

    def load(
        self,
        session: Session | None,
        *,
        context: ExecutionContext,
        task: AITaskType,
        sensitivity: SensitivityLevel,
    ) -> AIPolicyRuntimeSnapshot:
        return self._snapshot

    def validate_startup(
        self,
        session: Session,
        *,
        registered_tasks: frozenset[AITaskType],
    ) -> None:
        return None


def _override_rule(row: AIPolicyOverride) -> AIPolicyRule:
    task = AITaskType(row.task_id) if row.task_id is not None else None
    sensitivity = SensitivityLevel(row.sensitivity) if row.sensitivity is not None else None
    canonical = {
        "firm_id": str(row.firm_id),
        "client_id": str(row.client_id) if row.client_id is not None else None,
        "task": task.value if task is not None else None,
        "sensitivity": sensitivity.value if sensitivity is not None else None,
        "revision": row.revision,
        "constraints": row.constraints,
    }
    expected_hash = hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    if expected_hash != row.configuration_hash:
        raise InvalidAIPolicyConfiguration("tenant AI policy override hash mismatch")
    constraints = AIPolicyConstraints.model_validate(row.constraints, strict=False)
    return AIPolicyRule(
        rule_id=f"override:{row.id}",
        revision=row.revision,
        task=task,
        sensitivity=sensitivity,
        firm_id=row.firm_id,
        client_id=row.client_id,
        constraints=constraints,
        content_hash=row.configuration_hash,
    )


def _validate_runtime_control(control: AIPolicyRuntimeControl) -> None:
    canonical = {
        "task_id": control.task_id,
        "enabled": control.enabled,
        "revision": control.revision,
    }
    expected_hash = hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    if expected_hash != control.configuration_hash:
        raise InvalidAIPolicyConfiguration("AI policy runtime control hash mismatch")
