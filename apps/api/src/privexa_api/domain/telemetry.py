from __future__ import annotations

import json
import logging

from privexa_api.domain.events import DomainEvent

LOGGER = logging.getLogger("privexa.domain")
_HANDLER_NAME = "privexa-domain-json"


def configure_domain_logging() -> None:
    """Configure one content-free JSON-line logger for domain operation outcomes."""

    LOGGER.disabled = False
    LOGGER.setLevel(logging.INFO)
    LOGGER.propagate = False
    if not any(handler.get_name() == _HANDLER_NAME for handler in LOGGER.handlers):
        handler = logging.StreamHandler()
        handler.set_name(_HANDLER_NAME)
        handler.setFormatter(logging.Formatter("%(message)s"))
        LOGGER.addHandler(handler)


def log_committed_domain_event(event: DomainEvent) -> None:
    """Publish a content-free post-commit representation of an in-process domain event."""

    LOGGER.info(
        json.dumps(
            {
                "event": "domain.event_committed",
                "event_id": event.event_id,
                "event_type": event.event_type,
                "aggregate_type": event.aggregate_type,
                "aggregate_id": event.aggregate_id,
                "firm_id": event.firm_id,
                "client_id": event.client_id,
                "actor_user_id": event.actor_user_id,
                "actor_membership_id": event.actor_membership_id,
                "request_id": event.request_id,
                "trace_id": event.trace_id,
                "originating_channel": event.originating_channel,
                "occurred_at": event.occurred_at,
                "schema_version": event.schema_version,
                "payload_fields": sorted(event.payload),
            },
            sort_keys=True,
            default=str,
        )
    )
