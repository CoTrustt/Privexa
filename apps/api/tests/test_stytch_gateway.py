from types import SimpleNamespace

import pytest
import requests
from stytch.core.response_base import StytchError, StytchErrorDetails

from privexa_api.authentication.errors import (
    AuthenticationFailedError,
    AuthenticationServiceUnavailableError,
    SessionExpiredError,
)
from privexa_api.authentication.stytch_gateway import StytchB2BSessionGateway


class FakeSessions:
    def __init__(self, *, response=None, error: Exception | None = None) -> None:
        self.response = response
        self.error = error
        self.revoked: list[str] = []

    def authenticate(self, *, session_token: str):
        if self.error:
            raise self.error
        return self.response

    def revoke(self, *, session_token: str) -> None:
        if self.error:
            raise self.error
        self.revoked.append(session_token)


def _stytch_error(error_type: str, status_code: int) -> StytchError:
    return StytchError(
        StytchErrorDetails(
            status_code=status_code,
            request_id="request-test",
            error_type=error_type,
            error_message="provider detail must not escape",
        )
    )


def _gateway(sessions: FakeSessions) -> StytchB2BSessionGateway:
    gateway = object.__new__(StytchB2BSessionGateway)
    gateway._client = SimpleNamespace(sessions=sessions)
    return gateway


def test_authenticate_normalizes_the_current_stytch_response_shape() -> None:
    sessions = FakeSessions(
        response=SimpleNamespace(
            member=SimpleNamespace(member_id="member-test-1"),
            organization=SimpleNamespace(organization_id="organization-test-1"),
            member_session=SimpleNamespace(member_session_id="member-session-test-1"),
            request_id="request-test-1",
        )
    )

    result = _gateway(sessions).authenticate("opaque-token")

    assert result.member_id == "member-test-1"
    assert result.organization_id == "organization-test-1"
    assert result.member_session_id == "member-session-test-1"


@pytest.mark.parametrize(
    "response",
    [
        None,
        SimpleNamespace(
            member=SimpleNamespace(member_id=""),
            organization=SimpleNamespace(organization_id="organization-test-1"),
            member_session=SimpleNamespace(member_session_id="member-session-test-1"),
            request_id="request-test-1",
        ),
    ],
)
def test_authenticate_fails_closed_for_an_unexpected_provider_response(response) -> None:
    gateway = _gateway(FakeSessions(response=response))

    with pytest.raises(AuthenticationServiceUnavailableError):
        gateway.authenticate("opaque-token")


@pytest.mark.parametrize(
    ("error_type", "status_code", "expected"),
    [
        ("session_not_found", 404, SessionExpiredError),
        ("session_must_have_at_least_one_active_factor", 401, SessionExpiredError),
        ("invalid_session_token", 401, AuthenticationFailedError),
        ("server_unavailable", 503, AuthenticationServiceUnavailableError),
    ],
)
def test_authenticate_maps_current_stytch_errors_to_stable_domain_errors(
    error_type: str,
    status_code: int,
    expected: type[Exception],
) -> None:
    gateway = _gateway(FakeSessions(error=_stytch_error(error_type, status_code)))

    with pytest.raises(expected):
        gateway.authenticate("opaque-token")


@pytest.mark.parametrize("error", [TimeoutError(), requests.ConnectionError()])
def test_authenticate_maps_provider_transport_failures_to_unavailable(error: Exception) -> None:
    gateway = _gateway(FakeSessions(error=error))

    with pytest.raises(AuthenticationServiceUnavailableError):
        gateway.authenticate("opaque-token")


def test_revoke_is_idempotent_when_the_provider_session_is_already_gone() -> None:
    gateway = _gateway(FakeSessions(error=_stytch_error("session_not_found", 404)))

    gateway.revoke("opaque-token")
