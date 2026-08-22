from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from privexa_api.ai_gateway.models import AIProviderCircuitState, AIProviderRuntimeControl
from privexa_api.ai_gateway.routing import AIProviderName
from privexa_api.ai_policy.models import AIPolicyRuntimeControl
from privexa_api.ai_types import AITaskType
from privexa_api.config import get_database_url, get_settings


def set_global_ai(session: Session, *, enabled: bool) -> int:
    return _set_policy_control(session, task_id=None, enabled=enabled)


def set_task_ai(session: Session, *, task: AITaskType, enabled: bool) -> int:
    return _set_policy_control(session, task_id=task.value, enabled=enabled)


def set_provider_ai(session: Session, *, provider: AIProviderName, enabled: bool) -> int:
    current = session.scalar(
        select(AIProviderRuntimeControl)
        .where(
            AIProviderRuntimeControl.provider_id == provider.value,
            AIProviderRuntimeControl.superseded_at.is_(None),
        )
        .with_for_update()
    )
    if current is None:
        raise RuntimeError("current provider control is missing")
    if current.enabled is enabled:
        return current.revision
    now = datetime.now(UTC)
    current.superseded_at = now
    revision = current.revision + 1
    session.add(
        AIProviderRuntimeControl(
            provider_id=provider.value,
            enabled=enabled,
            revision=revision,
            configuration_hash=_hash(
                {
                    "provider_id": provider.value,
                    "enabled": enabled,
                    "revision": revision,
                }
            ),
            effective_at=now,
        )
    )
    return revision


def inspect_ai_controls(session: Session) -> dict[str, object]:
    """Return a bounded, read-only control snapshot suitable for deployment evidence."""
    policy_controls = session.scalars(
        select(AIPolicyRuntimeControl)
        .where(AIPolicyRuntimeControl.superseded_at.is_(None))
        .order_by(AIPolicyRuntimeControl.task_id.asc().nullsfirst())
    ).all()
    provider_controls = session.scalars(
        select(AIProviderRuntimeControl)
        .where(AIProviderRuntimeControl.superseded_at.is_(None))
        .order_by(AIProviderRuntimeControl.provider_id)
    ).all()
    circuits = session.scalars(
        select(AIProviderCircuitState).order_by(
            AIProviderCircuitState.provider_id,
            AIProviderCircuitState.scope_type,
            AIProviderCircuitState.provider_model,
        )
    ).all()
    return {
        "policy_controls": [
            {
                "scope": "global" if row.task_id is None else "task",
                "task_id": row.task_id,
                "enabled": row.enabled,
                "revision": row.revision,
                "configuration_valid": row.configuration_hash
                == _hash(
                    {
                        "task_id": row.task_id,
                        "enabled": row.enabled,
                        "revision": row.revision,
                    }
                ),
                "effective_at": row.effective_at.isoformat(),
            }
            for row in policy_controls
        ],
        "provider_controls": [
            {
                "provider_id": row.provider_id,
                "enabled": row.enabled,
                "revision": row.revision,
                "configuration_valid": row.configuration_hash
                == _hash(
                    {
                        "provider_id": row.provider_id,
                        "enabled": row.enabled,
                        "revision": row.revision,
                    }
                ),
                "effective_at": row.effective_at.isoformat(),
            }
            for row in provider_controls
        ],
        "circuits": [
            {
                "scope_type": row.scope_type,
                "provider_id": row.provider_id,
                "provider_model": row.provider_model or None,
                "state": row.state,
                "failure_count": row.failure_count,
                "opened_at": row.opened_at.isoformat() if row.opened_at else None,
                "probe_lease_until": (
                    row.probe_lease_until.isoformat() if row.probe_lease_until else None
                ),
            }
            for row in circuits
        ],
    }


def _set_policy_control(session: Session, *, task_id: str | None, enabled: bool) -> int:
    statement = select(AIPolicyRuntimeControl).where(AIPolicyRuntimeControl.superseded_at.is_(None))
    statement = statement.where(
        AIPolicyRuntimeControl.task_id.is_(None)
        if task_id is None
        else AIPolicyRuntimeControl.task_id == task_id
    ).with_for_update()
    current = session.scalar(statement)
    if current is None:
        raise RuntimeError("current AI policy control is missing")
    if current.enabled is enabled:
        return current.revision
    now = datetime.now(UTC)
    current.superseded_at = now
    revision = current.revision + 1
    session.add(
        AIPolicyRuntimeControl(
            task_id=task_id,
            enabled=enabled,
            revision=revision,
            configuration_hash=_hash(
                {"task_id": task_id, "enabled": enabled, "revision": revision}
            ),
            effective_at=now,
        )
    )
    return revision


def _hash(value: dict[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Mutate revisioned AI controls using schema-owner credentials."
    )
    subparsers = parser.add_subparsers(dest="scope", required=True)
    global_parser = subparsers.add_parser("global")
    global_parser.add_argument("state", choices=("enable", "disable"))
    task_parser = subparsers.add_parser("task")
    task_parser.add_argument("task", choices=tuple(item.value for item in AITaskType))
    task_parser.add_argument("state", choices=("enable", "disable"))
    provider_parser = subparsers.add_parser("provider")
    provider_parser.add_argument("provider", choices=tuple(item.value for item in AIProviderName))
    provider_parser.add_argument("state", choices=("enable", "disable"))
    subparsers.add_parser("status")
    args = parser.parse_args()

    engine = create_engine(get_database_url(), pool_pre_ping=True)
    try:
        with Session(engine) as session, session.begin():
            if args.scope == "status":
                settings = get_settings()
                snapshot = inspect_ai_controls(session)
                snapshot["environment"] = settings.environment
                snapshot["deployment_ceiling_enabled"] = settings.ai_gateway_enabled
                snapshot["provider_mode"] = settings.ai_provider_mode
                print(json.dumps(snapshot, sort_keys=True))
                return
            enabled = args.state == "enable"
            if args.scope == "global":
                revision = set_global_ai(session, enabled=enabled)
            elif args.scope == "task":
                revision = set_task_ai(
                    session,
                    task=AITaskType(args.task),
                    enabled=enabled,
                )
            else:
                revision = set_provider_ai(
                    session,
                    provider=AIProviderName(args.provider),
                    enabled=enabled,
                )
    finally:
        engine.dispose()
    print(f"AI {args.scope} control revision {revision} is now {args.state}d.")


if __name__ == "__main__":
    main()
