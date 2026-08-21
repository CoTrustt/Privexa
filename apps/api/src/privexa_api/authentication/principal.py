from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from privexa_api.access_control.context import FirmContext
from privexa_api.access_control.enums import FirmRole


@dataclass(frozen=True, slots=True)
class AuthenticatedPrincipal:
    """Trusted application identity produced after provider and domain validation."""

    firm_context: FirmContext
    stytch_member_id: str
    stytch_organization_id: str
    stytch_member_session_id: str

    @property
    def user_id(self) -> UUID:
        return self.firm_context.user_id

    @property
    def membership_id(self) -> UUID:
        return self.firm_context.membership_id

    @property
    def firm_id(self) -> UUID:
        return self.firm_context.firm_id

    @property
    def role(self) -> FirmRole:
        return self.firm_context.role
