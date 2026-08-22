from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class StoredFileKeys:
    upload_key: str
    storage_key: str


def build_stored_file_keys(*, firm_id: UUID, client_id: UUID, file_id: UUID) -> StoredFileKeys:
    tenant_path = f"firms/{firm_id}/clients/{client_id}/files/{file_id}"
    return StoredFileKeys(
        upload_key=f"staging/{tenant_path}/upload",
        storage_key=f"objects/{tenant_path}/original",
    )
