from __future__ import annotations

import hashlib
import json
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from privexa_api.ai_gateway.models import AIProviderRuntimeControl
from privexa_api.ai_gateway.routing import AIProviderName


class AIProviderControlError(RuntimeError):
    pass


class AIProviderControlRepository(Protocol):
    def is_enabled(self, provider: AIProviderName) -> bool: ...


class DatabaseAIProviderControlRepository:
    """Reads revisioned operator controls without caching emergency state."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def is_enabled(self, provider: AIProviderName) -> bool:
        with self._session_factory() as session, session.begin():
            rows = session.scalars(
                select(AIProviderRuntimeControl).where(
                    AIProviderRuntimeControl.provider_id == provider.value,
                    AIProviderRuntimeControl.superseded_at.is_(None),
                )
            ).all()
        if len(rows) != 1:
            raise AIProviderControlError("provider control is missing or ambiguous")
        row = rows[0]
        canonical = {
            "provider_id": row.provider_id,
            "enabled": row.enabled,
            "revision": row.revision,
        }
        expected = hashlib.sha256(
            json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        if expected != row.configuration_hash:
            raise AIProviderControlError("provider control hash mismatch")
        return row.enabled


class StaticAIProviderControlRepository:
    def __init__(self, enabled: dict[AIProviderName, bool] | None = None) -> None:
        self._enabled = dict(enabled or {})

    def is_enabled(self, provider: AIProviderName) -> bool:
        return self._enabled.get(provider, True)
