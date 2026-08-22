"""Deterministic contracts shared by Privexa professional domain objects."""

from privexa_api.domain.errors import (
    DomainIntegrityConflictError,
    DomainLifecycleConflictError,
    DomainProblem,
    DomainResourceNotFoundError,
    DomainValidationError,
    DomainVersionConflictError,
    TenantOwnershipMismatchError,
)
from privexa_api.domain.events import DomainEvent, DomainEventCollector
from privexa_api.domain.lifecycle import LifecyclePolicy

__all__ = [
    "DomainEvent",
    "DomainEventCollector",
    "DomainIntegrityConflictError",
    "DomainLifecycleConflictError",
    "DomainProblem",
    "DomainResourceNotFoundError",
    "DomainValidationError",
    "DomainVersionConflictError",
    "LifecyclePolicy",
    "TenantOwnershipMismatchError",
]
