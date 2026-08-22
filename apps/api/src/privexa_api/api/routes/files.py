from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from privexa_api.access_control.permissions import Permission
from privexa_api.api.authorization_dependencies import require_active_client_path_permission
from privexa_api.api.dependencies import get_database_session, get_stored_file_service
from privexa_api.api.errors import problem_response
from privexa_api.files.schemas import (
    CreateFileUploadRequest,
    CreateFileUploadResponse,
    DownloadFileResponse,
    SignedOperationResponse,
    StoredFileResponse,
    stored_file_response,
)
from privexa_api.files.service import StoredFileService
from privexa_api.security.execution_context import ExecutionContext

router = APIRouter(prefix="/clients/{client_id}/files", tags=["files"])

DatabaseSession = Annotated[Session, Depends(get_database_session)]
FileService = Annotated[StoredFileService, Depends(get_stored_file_service)]
FileCreateContext = Annotated[
    ExecutionContext,
    Depends(require_active_client_path_permission(Permission.FILE_CREATE)),
]
FileReadContext = Annotated[
    ExecutionContext,
    Depends(require_active_client_path_permission(Permission.FILE_READ)),
]
FileDeleteContext = Annotated[
    ExecutionContext,
    Depends(require_active_client_path_permission(Permission.FILE_DELETE)),
]


@router.post("/uploads", response_model=CreateFileUploadResponse, status_code=201)
def initiate_file_upload(
    payload: CreateFileUploadRequest,
    response: Response,
    context: FileCreateContext,
    session: DatabaseSession,
    service: FileService,
) -> CreateFileUploadResponse:
    initiation = service.initiate_upload(session, context=context, request=payload)
    response.headers["Cache-Control"] = "no-store"
    return CreateFileUploadResponse(
        file=stored_file_response(initiation.stored_file),
        upload=SignedOperationResponse(
            url=initiation.upload.url,
            method=initiation.upload.method,
            required_headers=initiation.upload.required_headers,
            expires_at=initiation.upload.expires_at,
        ),
    )


@router.post("/{file_id}/complete", response_model=StoredFileResponse)
def complete_file_upload(
    file_id: UUID,
    request: Request,
    response: Response,
    context: FileCreateContext,
    session: DatabaseSession,
    service: FileService,
) -> StoredFileResponse | JSONResponse:
    outcome = service.complete_upload(session, context=context, file_id=file_id)
    response.headers["Cache-Control"] = "no-store"
    if outcome.stored_file is None:
        return problem_response(
            request,
            status_code=409,
            code=outcome.problem_code or "FILE_UPLOAD_FAILED",
            title="File upload could not be completed",
            detail=outcome.problem_detail or "The file upload could not be completed.",
        )
    return stored_file_response(outcome.stored_file)


@router.get("/{file_id}", response_model=StoredFileResponse)
def get_file_metadata(
    file_id: UUID,
    response: Response,
    context: FileReadContext,
    session: DatabaseSession,
    service: FileService,
) -> StoredFileResponse:
    stored_file = service.get_metadata(session, context=context, file_id=file_id)
    response.headers["Cache-Control"] = "private, no-store"
    return stored_file_response(stored_file)


@router.post("/{file_id}/download", response_model=DownloadFileResponse)
def create_file_download(
    file_id: UUID,
    response: Response,
    context: FileReadContext,
    session: DatabaseSession,
    service: FileService,
) -> DownloadFileResponse:
    download = service.create_download(session, context=context, file_id=file_id)
    response.headers["Cache-Control"] = "no-store"
    return DownloadFileResponse(url=download.url, expires_at=download.expires_at)


@router.delete("/{file_id}", status_code=204)
def delete_file(
    file_id: UUID,
    response: Response,
    context: FileDeleteContext,
    session: DatabaseSession,
    service: FileService,
) -> None:
    service.delete(session, context=context, file_id=file_id)
    response.headers["Cache-Control"] = "no-store"
