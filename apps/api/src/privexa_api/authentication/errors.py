from __future__ import annotations


class AuthenticationProblem(Exception):
    def __init__(self, *, code: str, status_code: int, title: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.status_code = status_code
        self.title = title
        self.detail = detail


class AuthenticationRequiredError(AuthenticationProblem):
    def __init__(self) -> None:
        super().__init__(
            code="AUTHENTICATION_REQUIRED",
            status_code=401,
            title="Sign-in required",
            detail="Sign in to continue to Privexa.",
        )


class AuthenticationFailedError(AuthenticationProblem):
    def __init__(self) -> None:
        super().__init__(
            code="AUTHENTICATION_FAILED",
            status_code=401,
            title="Sign-in could not be verified",
            detail="Sign in again to continue.",
        )


class SessionExpiredError(AuthenticationProblem):
    def __init__(self) -> None:
        super().__init__(
            code="SESSION_EXPIRED",
            status_code=401,
            title="Session expired",
            detail="Your session has expired. Sign in again to continue.",
        )


class MemberNotProvisionedError(AuthenticationProblem):
    def __init__(self) -> None:
        super().__init__(
            code="MEMBER_NOT_PROVISIONED",
            status_code=403,
            title="Workspace access unavailable",
            detail="Your account is not connected to a Privexa workspace.",
        )


class MembershipInactiveError(AuthenticationProblem):
    def __init__(self) -> None:
        super().__init__(
            code="MEMBERSHIP_INACTIVE",
            status_code=403,
            title="Account access inactive",
            detail="Your account does not currently have access to this Privexa workspace.",
        )


class FirmInactiveError(AuthenticationProblem):
    def __init__(self) -> None:
        super().__init__(
            code="FIRM_INACTIVE",
            status_code=403,
            title="Workspace unavailable",
            detail="This Privexa workspace is currently unavailable.",
        )


class AuthenticationServiceUnavailableError(AuthenticationProblem):
    def __init__(self) -> None:
        super().__init__(
            code="AUTHENTICATION_SERVICE_UNAVAILABLE",
            status_code=503,
            title="Sign-in temporarily unavailable",
            detail="Privexa could not verify your session. Try again shortly.",
        )
