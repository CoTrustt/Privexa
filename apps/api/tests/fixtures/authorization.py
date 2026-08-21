from __future__ import annotations

from dataclasses import dataclass, field

from fixtures.tenant_foundation import (
    STYTCH_ALICE_ID,
    STYTCH_ANITA_ID,
    STYTCH_BOB_ID,
    STYTCH_DAVID_ID,
    STYTCH_FIRM_A_ID,
    STYTCH_FIRM_B_ADMIN_ID,
    STYTCH_FIRM_B_ID,
    STYTCH_RAHUL_ID,
)
from privexa_api.authentication.errors import AuthenticationFailedError, SessionExpiredError
from privexa_api.authentication.stytch_gateway import ValidatedStytchSession


@dataclass(frozen=True, slots=True)
class TestIdentity:
    member_id: str
    organization_id: str


TEST_IDENTITIES = {
    "alice-token": TestIdentity(STYTCH_ALICE_ID, STYTCH_FIRM_A_ID),
    "anita-token": TestIdentity(STYTCH_ANITA_ID, STYTCH_FIRM_A_ID),
    "rahul-token": TestIdentity(STYTCH_RAHUL_ID, STYTCH_FIRM_A_ID),
    "david-token": TestIdentity(STYTCH_DAVID_ID, STYTCH_FIRM_A_ID),
    "bob-token": TestIdentity(STYTCH_BOB_ID, STYTCH_FIRM_B_ID),
    "firm-b-admin-token": TestIdentity(STYTCH_FIRM_B_ADMIN_ID, STYTCH_FIRM_B_ID),
    "unprovisioned-token": TestIdentity("member-not-provisioned", STYTCH_FIRM_A_ID),
}


@dataclass
class MultiIdentityStytchGateway:
    """Closest test abstraction to Stytch: tokens yield only validated provider IDs."""

    revoked_tokens: set[str] = field(default_factory=set)

    def authenticate(self, session_token: str) -> ValidatedStytchSession:
        if session_token == "expired-token" or session_token in self.revoked_tokens:
            raise SessionExpiredError
        if session_token == "invalid-token":
            raise AuthenticationFailedError
        identity = TEST_IDENTITIES.get(session_token)
        if identity is None:
            raise AuthenticationFailedError
        return ValidatedStytchSession(
            member_id=identity.member_id,
            organization_id=identity.organization_id,
            member_session_id=f"session-{identity.member_id}",
            request_id=f"request-{identity.member_id}",
        )

    def revoke(self, session_token: str) -> None:
        self.revoked_tokens.add(session_token)
