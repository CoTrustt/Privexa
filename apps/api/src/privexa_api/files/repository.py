from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from privexa_api.access_control.context import ClientContext
from privexa_api.files.models import StoredFile


class StoredFileRepository:
    @staticmethod
    def add(session: Session, *, stored_file: StoredFile) -> StoredFile:
        session.add(stored_file)
        session.flush()
        return stored_file

    @staticmethod
    def get(
        session: Session,
        *,
        context: ClientContext,
        file_id: UUID,
        for_update: bool = False,
    ) -> StoredFile | None:
        statement = select(StoredFile).where(
            StoredFile.id == file_id,
            StoredFile.firm_id == context.firm_id,
            StoredFile.client_id == context.client_id,
        )
        if for_update:
            statement = statement.with_for_update()
        return session.scalar(statement)
