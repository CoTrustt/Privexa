from __future__ import annotations

from uuid import UUID


class DatabaseSecurityError(Exception):
    """Base failure for database security configuration or tenant context."""

    def __init__(
        self,
        *,
        code: str,
        firm_id: UUID | None = None,
        client_id: UUID | None = None,
    ) -> None:
        super().__init__(code)
        self.code = code
        self.firm_id = firm_id
        self.client_id = client_id


class TenantContextConflictError(DatabaseSecurityError):
    def __init__(self, *, firm_id: UUID, client_id: UUID | None = None) -> None:
        super().__init__(
            code="TENANT_CONTEXT_CONFLICT",
            firm_id=firm_id,
            client_id=client_id,
        )


class TenantContextTransactionError(DatabaseSecurityError):
    def __init__(self, *, firm_id: UUID, client_id: UUID | None = None) -> None:
        super().__init__(
            code="TENANT_CONTEXT_TRANSACTION_INVALID",
            firm_id=firm_id,
            client_id=client_id,
        )


class RuntimeDatabaseSecurityError(DatabaseSecurityError):
    def __init__(self, *, code: str) -> None:
        super().__init__(code=code)
