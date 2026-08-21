from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from privexa_api.access_control.enums import (
    ClientAccessStatus,
    FirmRole,
    MembershipStatus,
)
from privexa_api.access_control.models import ClientAccessGrant, FirmMembership
from privexa_api.clients.enums import ClientWorkspaceStatus
from privexa_api.clients.models import ClientWorkspace
from privexa_api.identity.enums import FirmStatus, UserStatus
from privexa_api.identity.models import Firm, User

_ASSIGNMENT_ROLES = frozenset({FirmRole.CONSULTANT, FirmRole.REVIEWER, FirmRole.READ_ONLY})


class DevelopmentProvisioningError(ValueError):
    """A safe, actionable local provisioning failure."""


@dataclass(frozen=True, slots=True)
class DevelopmentIdentitySpec:
    firm_name: str
    stytch_organization_id: str
    email: str
    display_name: str
    role: FirmRole
    stytch_member_id: str
    client_names: tuple[str, ...] = ()
    assigned_client_names: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ProvisionedDevelopmentIdentity:
    firm_id: UUID
    user_id: UUID
    membership_id: UUID
    client_ids: dict[str, UUID]
    assigned_client_ids: dict[str, UUID]


def _required_text(value: str, *, field: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise DevelopmentProvisioningError(f"{field} must not be blank")
    return normalized


def _normalize_spec(spec: DevelopmentIdentitySpec) -> DevelopmentIdentitySpec:
    email = _required_text(spec.email, field="email").lower()
    if "@" not in email:
        raise DevelopmentProvisioningError("email must contain '@'")
    organization_id = _required_text(
        spec.stytch_organization_id,
        field="stytch_organization_id",
    )
    member_id = _required_text(spec.stytch_member_id, field="stytch_member_id")
    if not organization_id.startswith("organization-"):
        raise DevelopmentProvisioningError("stytch_organization_id must start with 'organization-'")
    if not member_id.startswith("member-"):
        raise DevelopmentProvisioningError("stytch_member_id must start with 'member-'")

    client_names = tuple(
        dict.fromkeys(_required_text(name, field="client name") for name in spec.client_names)
    )
    assigned_client_names = tuple(
        dict.fromkeys(
            _required_text(name, field="assigned client name")
            for name in spec.assigned_client_names
        )
    )
    if assigned_client_names and spec.role not in _ASSIGNMENT_ROLES:
        raise DevelopmentProvisioningError(
            "Firm Owner and Firm Admin access all same-firm clients and must not receive "
            "redundant client assignments"
        )

    return DevelopmentIdentitySpec(
        firm_name=_required_text(spec.firm_name, field="firm_name"),
        stytch_organization_id=organization_id,
        email=email,
        display_name=_required_text(spec.display_name, field="display_name"),
        role=spec.role,
        stytch_member_id=member_id,
        client_names=client_names,
        assigned_client_names=assigned_client_names,
    )


def _resolve_firm(session: Session, spec: DevelopmentIdentitySpec) -> Firm:
    external_match = session.scalar(
        select(Firm).where(Firm.stytch_organization_id == spec.stytch_organization_id)
    )
    name_matches = session.scalars(select(Firm).where(Firm.name == spec.firm_name)).all()
    if len(name_matches) > 1:
        raise DevelopmentProvisioningError(
            f"Multiple firms already use the name {spec.firm_name!r}"
        )
    name_match = name_matches[0] if name_matches else None

    if external_match is not None and name_match not in {None, external_match}:
        raise DevelopmentProvisioningError(
            "The requested Stytch organization and firm name identify different firms"
        )
    firm = external_match or name_match
    if firm is None:
        firm = Firm(
            name=spec.firm_name,
            stytch_organization_id=spec.stytch_organization_id,
        )
        session.add(firm)
        session.flush()
    elif firm.stytch_organization_id not in {None, spec.stytch_organization_id}:
        raise DevelopmentProvisioningError(
            f"Firm {spec.firm_name!r} is bound to another Stytch organization"
        )
    else:
        firm.stytch_organization_id = spec.stytch_organization_id
        firm.status = FirmStatus.ACTIVE
        firm.archived_at = None
    return firm


def _resolve_user(session: Session, spec: DevelopmentIdentitySpec) -> User:
    user = session.scalar(select(User).where(User.email == spec.email))
    if user is None:
        user = User(email=spec.email, display_name=spec.display_name)
        session.add(user)
        session.flush()
    else:
        user.display_name = spec.display_name
        user.status = UserStatus.ACTIVE
    return user


def _resolve_membership(
    session: Session,
    *,
    firm: Firm,
    user: User,
    spec: DevelopmentIdentitySpec,
) -> FirmMembership:
    member_binding = session.scalar(
        select(FirmMembership).where(FirmMembership.stytch_member_id == spec.stytch_member_id)
    )
    membership = session.scalar(
        select(FirmMembership).where(
            FirmMembership.firm_id == firm.id,
            FirmMembership.user_id == user.id,
        )
    )
    if member_binding is not None and member_binding is not membership:
        raise DevelopmentProvisioningError(
            "The requested Stytch member is already bound to another Privexa membership"
        )
    if membership is None:
        membership = FirmMembership(
            firm_id=firm.id,
            user_id=user.id,
            role=spec.role,
            stytch_member_id=spec.stytch_member_id,
        )
        session.add(membership)
        session.flush()
    elif membership.stytch_member_id not in {None, spec.stytch_member_id}:
        raise DevelopmentProvisioningError(
            "The requested Privexa membership is bound to another Stytch member"
        )
    else:
        membership.role = spec.role
        membership.status = MembershipStatus.ACTIVE
        membership.revoked_at = None
        membership.stytch_member_id = spec.stytch_member_id
    return membership


def _resolve_client(session: Session, *, firm: Firm, name: str) -> ClientWorkspace:
    matches = session.scalars(
        select(ClientWorkspace).where(
            ClientWorkspace.firm_id == firm.id,
            ClientWorkspace.name == name,
        )
    ).all()
    if len(matches) > 1:
        raise DevelopmentProvisioningError(
            f"Multiple client workspaces already use the name {name!r} in this firm"
        )
    if matches:
        client = matches[0]
        client.status = ClientWorkspaceStatus.ACTIVE
        client.archived_at = None
        return client
    client = ClientWorkspace(firm_id=firm.id, name=name)
    session.add(client)
    session.flush()
    return client


def _resolve_assignment(
    session: Session,
    *,
    firm: Firm,
    membership: FirmMembership,
    client: ClientWorkspace,
) -> ClientAccessGrant:
    grant = session.scalar(
        select(ClientAccessGrant).where(
            ClientAccessGrant.firm_id == firm.id,
            ClientAccessGrant.membership_id == membership.id,
            ClientAccessGrant.client_id == client.id,
        )
    )
    if grant is None:
        grant = ClientAccessGrant(
            firm_id=firm.id,
            membership_id=membership.id,
            client_id=client.id,
        )
        session.add(grant)
    else:
        grant.status = ClientAccessStatus.ACTIVE
        grant.revoked_at = None
    return grant


def provision_development_identity(
    session: Session,
    *,
    spec: DevelopmentIdentitySpec,
) -> ProvisionedDevelopmentIdentity:
    """Create or reconcile one explicitly authorized local development identity."""

    normalized = _normalize_spec(spec)
    firm = _resolve_firm(session, normalized)
    user = _resolve_user(session, normalized)
    membership = _resolve_membership(
        session,
        firm=firm,
        user=user,
        spec=normalized,
    )

    requested_client_names = tuple(
        dict.fromkeys((*normalized.client_names, *normalized.assigned_client_names))
    )
    clients = {
        name: _resolve_client(session, firm=firm, name=name) for name in requested_client_names
    }
    assigned_clients = {name: clients[name] for name in normalized.assigned_client_names}
    for client in assigned_clients.values():
        _resolve_assignment(
            session,
            firm=firm,
            membership=membership,
            client=client,
        )
    session.flush()

    return ProvisionedDevelopmentIdentity(
        firm_id=firm.id,
        user_id=user.id,
        membership_id=membership.id,
        client_ids={name: client.id for name, client in clients.items()},
        assigned_client_ids={name: client.id for name, client in assigned_clients.items()},
    )
