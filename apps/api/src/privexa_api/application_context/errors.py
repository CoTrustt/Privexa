from __future__ import annotations


class ApplicationContextProblem(Exception):
    def __init__(self, *, code: str, status_code: int, title: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.status_code = status_code
        self.title = title
        self.detail = detail


class ActiveClientRequiredError(ApplicationContextProblem):
    def __init__(self) -> None:
        super().__init__(
            code="ACTIVE_CLIENT_REQUIRED",
            status_code=409,
            title="Choose a client workspace",
            detail="Choose an available client workspace before continuing.",
        )
