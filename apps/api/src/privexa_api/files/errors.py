from __future__ import annotations


class FileProblem(Exception):
    def __init__(
        self,
        *,
        status_code: int,
        code: str,
        title: str,
        detail: str,
    ) -> None:
        super().__init__(code)
        self.status_code = status_code
        self.code = code
        self.title = title
        self.detail = detail


class FileNotFoundError(FileProblem):
    def __init__(self) -> None:
        super().__init__(
            status_code=404,
            code="RESOURCE_NOT_FOUND",
            title="Resource not found",
            detail="The requested resource could not be found.",
        )


class FileStateConflictError(FileProblem):
    def __init__(self, *, code: str, detail: str) -> None:
        super().__init__(
            status_code=409,
            code=code,
            title="File is not available for this operation",
            detail=detail,
        )


class FileStorageUnavailableError(FileProblem):
    def __init__(self) -> None:
        super().__init__(
            status_code=503,
            code="STORAGE_TEMPORARILY_UNAVAILABLE",
            title="File storage temporarily unavailable",
            detail="Privexa could not safely complete the storage operation. Try again shortly.",
        )


class FileValidationError(FileProblem):
    def __init__(self, *, code: str, detail: str) -> None:
        super().__init__(
            status_code=422,
            code=code,
            title="File metadata is invalid",
            detail=detail,
        )
