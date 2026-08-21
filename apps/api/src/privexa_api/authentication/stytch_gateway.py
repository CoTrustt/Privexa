from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import requests
import stytch
from stytch.core.response_base import StytchError

from privexa_api.authentication.errors import (
    AuthenticationFailedError,
    AuthenticationServiceUnavailableError,
    SessionExpiredError,
)


@dataclass(frozen=True, slots=True)
class ValidatedStytchSession:
    member_id: str
    organization_id: str
    member_session_id: str
    request_id: str


class StytchSessionGateway(Protocol):
    def authenticate(self, session_token: str) -> ValidatedStytchSession: ...

    def revoke(self, session_token: str) -> None: ...


_EXPIRED_ERROR_TYPES = frozenset(
    {
        "session_not_found",
        "session_must_have_at_least_one_active_factor",
    }
)


class StytchB2BSessionGateway:
    def __init__(self, *, project_id: str, secret: str) -> None:
        self._client = stytch.B2BClient(project_id=project_id, secret=secret)

    def authenticate(self, session_token: str) -> ValidatedStytchSession:
        try:
            response = self._client.sessions.authenticate(session_token=session_token)
        except StytchError as error:
            error_type = error.details.error_type or ""
            if error_type in _EXPIRED_ERROR_TYPES or "expired" in error_type:
                raise SessionExpiredError from error
            if error.details.status_code in {400, 401, 404}:
                raise AuthenticationFailedError from error
            raise AuthenticationServiceUnavailableError from error
        except (requests.RequestException, TimeoutError):
            raise AuthenticationServiceUnavailableError from None

        try:
            validated_session = ValidatedStytchSession(
                member_id=response.member.member_id,
                organization_id=response.organization.organization_id,
                member_session_id=response.member_session.member_session_id,
                request_id=response.request_id,
            )
        except (AttributeError, TypeError):
            raise AuthenticationServiceUnavailableError from None

        if not all(
            isinstance(value, str) and value
            for value in (
                validated_session.member_id,
                validated_session.organization_id,
                validated_session.member_session_id,
                validated_session.request_id,
            )
        ):
            raise AuthenticationServiceUnavailableError
        return validated_session

    def revoke(self, session_token: str) -> None:
        try:
            self._client.sessions.revoke(session_token=session_token)
        except StytchError as error:
            if error.details.status_code in {400, 401, 404}:
                return
            raise AuthenticationServiceUnavailableError from error
        except (requests.RequestException, TimeoutError):
            raise AuthenticationServiceUnavailableError from None
