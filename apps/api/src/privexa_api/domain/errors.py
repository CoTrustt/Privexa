from __future__ import annotations

import re
from enum import StrEnum
from typing import Final

_STABLE_CODE = re.compile(r"^[A-Z][A-Z0-9_]{2,63}$")


class DomainProblemKind(StrEnum):
    VALIDATION = "VALIDATION"
    NOT_FOUND = "NOT_FOUND"
    LIFECYCLE_CONFLICT = "LIFECYCLE_CONFLICT"
    VERSION_CONFLICT = "VERSION_CONFLICT"
    INTEGRITY_CONFLICT = "INTEGRITY_CONFLICT"


class DomainProblem(Exception):
    """Safe deterministic failure raised by professional-object application services."""

    def __init__(
        self,
        *,
        kind: DomainProblemKind,
        code: str,
        title: str,
        detail: str,
        diagnostic_code: str | None = None,
    ) -> None:
        if not _STABLE_CODE.fullmatch(code):
            raise ValueError("domain error code must be a stable uppercase identifier")
        if diagnostic_code is not None and not _STABLE_CODE.fullmatch(diagnostic_code):
            raise ValueError("diagnostic code must be a stable uppercase identifier")
        super().__init__(code)
        self.kind = kind
        self.code = code
        self.title = title
        self.detail = detail
        self.diagnostic_code = diagnostic_code or code


class DomainValidationError(DomainProblem):
    def __init__(
        self,
        *,
        code: str = "DOMAIN_VALIDATION_FAILED",
        detail: str = "The requested change is not valid.",
    ) -> None:
        super().__init__(
            kind=DomainProblemKind.VALIDATION,
            code=code,
            title="Invalid professional record",
            detail=detail,
        )


class DomainResourceNotFoundError(DomainProblem):
    def __init__(self) -> None:
        super().__init__(
            kind=DomainProblemKind.NOT_FOUND,
            code="RESOURCE_NOT_FOUND",
            title="Resource not found",
            detail="The requested resource could not be found.",
        )


class TenantOwnershipMismatchError(DomainProblem):
    """Fail closed without confirming that a foreign tenant resource exists."""

    DIAGNOSTIC_CODE: Final = "TENANT_OWNERSHIP_MISMATCH"

    def __init__(self) -> None:
        super().__init__(
            kind=DomainProblemKind.NOT_FOUND,
            code="RESOURCE_NOT_FOUND",
            title="Resource not found",
            detail="The requested resource could not be found.",
            diagnostic_code=self.DIAGNOSTIC_CODE,
        )


class DomainLifecycleConflictError(DomainProblem):
    def __init__(self) -> None:
        super().__init__(
            kind=DomainProblemKind.LIFECYCLE_CONFLICT,
            code="LIFECYCLE_CONFLICT",
            title="Lifecycle transition not permitted",
            detail="The resource cannot move to the requested state from its current state.",
        )


class DomainVersionConflictError(DomainProblem):
    def __init__(self) -> None:
        super().__init__(
            kind=DomainProblemKind.VERSION_CONFLICT,
            code="VERSION_CONFLICT",
            title="Resource was modified",
            detail="The resource was modified by another operation. Refresh and try again.",
        )


class DomainIntegrityConflictError(DomainProblem):
    def __init__(self, *, code: str = "INTEGRITY_CONFLICT") -> None:
        super().__init__(
            kind=DomainProblemKind.INTEGRITY_CONFLICT,
            code=code,
            title="Resource conflict",
            detail="The requested change conflicts with an existing resource.",
        )
