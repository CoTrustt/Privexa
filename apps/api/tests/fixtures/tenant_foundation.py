from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.orm import Session

from privexa_api.access_control.enums import FirmRole, MembershipStatus
from privexa_api.access_control.models import ClientAccessGrant, FirmMembership
from privexa_api.clients.models import ClientWorkspace
from privexa_api.identity.models import Firm, User

FIRM_A_ID = UUID("00000000-0000-4000-8000-000000000001")
APOLLO_FINANCE_ID = UUID("00000000-0000-4000-8000-000000000002")
ALICE_ID = UUID("00000000-0000-4000-8000-000000000003")
ALICE_MEMBERSHIP_ID = UUID("00000000-0000-4000-8000-000000000004")
ALICE_APOLLO_GRANT_ID = UUID("00000000-0000-4000-8000-000000000005")
CAROL_ID = UUID("00000000-0000-4000-8000-000000000006")
CAROL_MEMBERSHIP_ID = UUID("00000000-0000-4000-8000-000000000007")
CAROL_APOLLO_GRANT_ID = UUID("00000000-0000-4000-8000-000000000008")
ACME_HEALTHCARE_ID = UUID("00000000-0000-4000-8000-000000000009")
ALICE_ACME_GRANT_ID = UUID("00000000-0000-4000-8000-000000000010")
MERIDIAN_RETAIL_ID = UUID("00000000-0000-4000-8000-000000000011")
VISHANT_ID = UUID("00000000-0000-4000-8000-000000000012")
VISHANT_MEMBERSHIP_ID = UUID("00000000-0000-4000-8000-000000000013")
DAVID_ID = UUID("00000000-0000-4000-8000-000000000014")
DAVID_MEMBERSHIP_ID = UUID("00000000-0000-4000-8000-000000000015")
MARK_ID = UUID("00000000-0000-4000-8000-000000000016")
MARK_MEMBERSHIP_ID = UUID("00000000-0000-4000-8000-000000000017")
MARK_ACME_GRANT_ID = UUID("00000000-0000-4000-8000-000000000018")
ANITA_ID = UUID("00000000-0000-4000-8000-000000000019")
ANITA_MEMBERSHIP_ID = UUID("00000000-0000-4000-8000-000000000020")
ANITA_APOLLO_GRANT_ID = UUID("00000000-0000-4000-8000-000000000021")
RAHUL_ID = UUID("00000000-0000-4000-8000-000000000022")
RAHUL_MEMBERSHIP_ID = UUID("00000000-0000-4000-8000-000000000023")
RAHUL_ACME_GRANT_ID = UUID("00000000-0000-4000-8000-000000000024")
INACTIVE_MEMBER_ID = UUID("00000000-0000-4000-8000-000000000025")
INACTIVE_MEMBERSHIP_ID = UUID("00000000-0000-4000-8000-000000000026")

FIRM_B_ID = UUID("00000000-0000-4000-8000-000000000101")
NORTHSTAR_RETAIL_ID = UUID("00000000-0000-4000-8000-000000000102")
BOB_ID = UUID("00000000-0000-4000-8000-000000000103")
BOB_MEMBERSHIP_ID = UUID("00000000-0000-4000-8000-000000000104")
BOB_NORTHSTAR_GRANT_ID = UUID("00000000-0000-4000-8000-000000000105")
FIRM_B_ADMIN_ID = UUID("00000000-0000-4000-8000-000000000106")
FIRM_B_ADMIN_MEMBERSHIP_ID = UUID("00000000-0000-4000-8000-000000000107")

STYTCH_FIRM_A_ID = "organization-test-firm-a"
STYTCH_FIRM_B_ID = "organization-test-firm-b"
STYTCH_ALICE_ID = "member-test-alice"
STYTCH_BOB_ID = "member-test-bob"
STYTCH_DAVID_ID = "member-test-david"
STYTCH_ANITA_ID = "member-test-anita"
STYTCH_RAHUL_ID = "member-test-rahul"
STYTCH_FIRM_B_ADMIN_ID = "member-test-firm-b-admin"


@dataclass(frozen=True, slots=True)
class TenantFoundationFixture:
    firm_a: Firm
    apollo_finance: ClientWorkspace
    acme_healthcare: ClientWorkspace
    meridian_retail: ClientWorkspace
    vishant: User
    vishant_membership: FirmMembership
    david: User
    david_membership: FirmMembership
    mark: User
    mark_membership: FirmMembership
    mark_acme_grant: ClientAccessGrant
    anita: User
    anita_membership: FirmMembership
    anita_apollo_grant: ClientAccessGrant
    rahul: User
    rahul_membership: FirmMembership
    rahul_acme_grant: ClientAccessGrant
    inactive_member: User
    inactive_membership: FirmMembership
    alice: User
    alice_membership: FirmMembership
    alice_apollo_grant: ClientAccessGrant
    alice_acme_grant: ClientAccessGrant
    carol: User
    carol_membership: FirmMembership
    carol_apollo_grant: ClientAccessGrant
    firm_b: Firm
    northstar_retail: ClientWorkspace
    bob: User
    bob_membership: FirmMembership
    bob_northstar_grant: ClientAccessGrant
    firm_b_admin: User
    firm_b_admin_membership: FirmMembership


def persist_tenant_foundation_fixture(session: Session) -> TenantFoundationFixture:
    """Persist deterministic tenants, roles, assignments, and unassigned clients."""
    firm_a = Firm(
        id=FIRM_A_ID,
        name="Pai Privacy Consulting",
        stytch_organization_id=STYTCH_FIRM_A_ID,
    )
    apollo_finance = ClientWorkspace(
        id=APOLLO_FINANCE_ID,
        firm_id=FIRM_A_ID,
        name="Apollo Finance",
    )
    acme_healthcare = ClientWorkspace(
        id=ACME_HEALTHCARE_ID,
        firm_id=FIRM_A_ID,
        name="Acme Healthcare",
    )
    meridian_retail = ClientWorkspace(
        id=MERIDIAN_RETAIL_ID,
        firm_id=FIRM_A_ID,
        name="Meridian Retail",
    )
    vishant = User(
        id=VISHANT_ID,
        email="vishant@firm-a.test",
        display_name="Firm Owner Vishant",
    )
    vishant_membership = FirmMembership(
        id=VISHANT_MEMBERSHIP_ID,
        firm_id=FIRM_A_ID,
        user_id=VISHANT_ID,
        role=FirmRole.FIRM_OWNER,
    )
    david = User(
        id=DAVID_ID,
        email="david@firm-a.test",
        display_name="Firm Admin David",
    )
    david_membership = FirmMembership(
        id=DAVID_MEMBERSHIP_ID,
        firm_id=FIRM_A_ID,
        user_id=DAVID_ID,
        role=FirmRole.FIRM_ADMIN,
        stytch_member_id=STYTCH_DAVID_ID,
    )
    mark = User(
        id=MARK_ID,
        email="mark@firm-a.test",
        display_name="Read Only Mark",
    )
    mark_membership = FirmMembership(
        id=MARK_MEMBERSHIP_ID,
        firm_id=FIRM_A_ID,
        user_id=MARK_ID,
        role=FirmRole.READ_ONLY,
    )
    mark_acme_grant = ClientAccessGrant(
        id=MARK_ACME_GRANT_ID,
        firm_id=FIRM_A_ID,
        client_id=ACME_HEALTHCARE_ID,
        membership_id=MARK_MEMBERSHIP_ID,
    )
    anita = User(id=ANITA_ID, email="anita@firm-a.test", display_name="Consultant Anita")
    anita_membership = FirmMembership(
        id=ANITA_MEMBERSHIP_ID,
        firm_id=FIRM_A_ID,
        user_id=ANITA_ID,
        role=FirmRole.CONSULTANT,
        stytch_member_id=STYTCH_ANITA_ID,
    )
    anita_apollo_grant = ClientAccessGrant(
        id=ANITA_APOLLO_GRANT_ID,
        firm_id=FIRM_A_ID,
        client_id=APOLLO_FINANCE_ID,
        membership_id=ANITA_MEMBERSHIP_ID,
    )
    rahul = User(id=RAHUL_ID, email="rahul@firm-a.test", display_name="Consultant Rahul")
    rahul_membership = FirmMembership(
        id=RAHUL_MEMBERSHIP_ID,
        firm_id=FIRM_A_ID,
        user_id=RAHUL_ID,
        role=FirmRole.CONSULTANT,
        stytch_member_id=STYTCH_RAHUL_ID,
    )
    rahul_acme_grant = ClientAccessGrant(
        id=RAHUL_ACME_GRANT_ID,
        firm_id=FIRM_A_ID,
        client_id=ACME_HEALTHCARE_ID,
        membership_id=RAHUL_MEMBERSHIP_ID,
    )
    inactive_member = User(
        id=INACTIVE_MEMBER_ID,
        email="inactive@firm-a.test",
        display_name="Inactive Member",
    )
    inactive_membership = FirmMembership(
        id=INACTIVE_MEMBERSHIP_ID,
        firm_id=FIRM_A_ID,
        user_id=INACTIVE_MEMBER_ID,
        role=FirmRole.CONSULTANT,
        status=MembershipStatus.SUSPENDED,
    )
    alice = User(id=ALICE_ID, email="alice@firm-a.test", display_name="Consultant Alice")
    alice_membership = FirmMembership(
        id=ALICE_MEMBERSHIP_ID,
        firm_id=FIRM_A_ID,
        user_id=ALICE_ID,
        role=FirmRole.CONSULTANT,
        stytch_member_id=STYTCH_ALICE_ID,
    )
    alice_apollo_grant = ClientAccessGrant(
        id=ALICE_APOLLO_GRANT_ID,
        firm_id=FIRM_A_ID,
        client_id=APOLLO_FINANCE_ID,
        membership_id=ALICE_MEMBERSHIP_ID,
    )
    alice_acme_grant = ClientAccessGrant(
        id=ALICE_ACME_GRANT_ID,
        firm_id=FIRM_A_ID,
        client_id=ACME_HEALTHCARE_ID,
        membership_id=ALICE_MEMBERSHIP_ID,
    )
    carol = User(
        id=CAROL_ID,
        email="carol@firm-a.test",
        display_name="Reviewer Carol",
    )
    carol_membership = FirmMembership(
        id=CAROL_MEMBERSHIP_ID,
        firm_id=FIRM_A_ID,
        user_id=CAROL_ID,
        role=FirmRole.REVIEWER,
    )
    carol_apollo_grant = ClientAccessGrant(
        id=CAROL_APOLLO_GRANT_ID,
        firm_id=FIRM_A_ID,
        client_id=APOLLO_FINANCE_ID,
        membership_id=CAROL_MEMBERSHIP_ID,
    )

    firm_b = Firm(
        id=FIRM_B_ID,
        name="Northstar Privacy Advisors",
        stytch_organization_id=STYTCH_FIRM_B_ID,
    )
    northstar_retail = ClientWorkspace(
        id=NORTHSTAR_RETAIL_ID,
        firm_id=FIRM_B_ID,
        name="Northstar Retail",
    )
    bob = User(id=BOB_ID, email="bob@firm-b.test", display_name="Consultant Bob")
    bob_membership = FirmMembership(
        id=BOB_MEMBERSHIP_ID,
        firm_id=FIRM_B_ID,
        user_id=BOB_ID,
        role=FirmRole.CONSULTANT,
        stytch_member_id=STYTCH_BOB_ID,
    )
    bob_northstar_grant = ClientAccessGrant(
        id=BOB_NORTHSTAR_GRANT_ID,
        firm_id=FIRM_B_ID,
        client_id=NORTHSTAR_RETAIL_ID,
        membership_id=BOB_MEMBERSHIP_ID,
    )
    firm_b_admin = User(
        id=FIRM_B_ADMIN_ID,
        email="admin@firm-b.test",
        display_name="Firm B Admin",
    )
    firm_b_admin_membership = FirmMembership(
        id=FIRM_B_ADMIN_MEMBERSHIP_ID,
        firm_id=FIRM_B_ID,
        user_id=FIRM_B_ADMIN_ID,
        role=FirmRole.FIRM_ADMIN,
        stytch_member_id=STYTCH_FIRM_B_ADMIN_ID,
    )

    session.add_all(
        [
            firm_a,
            firm_b,
            vishant,
            david,
            mark,
            anita,
            rahul,
            inactive_member,
            alice,
            carol,
            bob,
            firm_b_admin,
        ]
    )
    session.flush()
    session.add_all(
        [
            alice_membership,
            vishant_membership,
            david_membership,
            mark_membership,
            anita_membership,
            rahul_membership,
            inactive_membership,
            carol_membership,
            bob_membership,
            firm_b_admin_membership,
            apollo_finance,
            acme_healthcare,
            meridian_retail,
            northstar_retail,
        ]
    )
    session.flush()
    session.add_all(
        [
            alice_apollo_grant,
            alice_acme_grant,
            carol_apollo_grant,
            mark_acme_grant,
            anita_apollo_grant,
            rahul_acme_grant,
            bob_northstar_grant,
        ]
    )
    session.flush()

    return TenantFoundationFixture(
        firm_a=firm_a,
        apollo_finance=apollo_finance,
        acme_healthcare=acme_healthcare,
        meridian_retail=meridian_retail,
        vishant=vishant,
        vishant_membership=vishant_membership,
        david=david,
        david_membership=david_membership,
        mark=mark,
        mark_membership=mark_membership,
        mark_acme_grant=mark_acme_grant,
        anita=anita,
        anita_membership=anita_membership,
        anita_apollo_grant=anita_apollo_grant,
        rahul=rahul,
        rahul_membership=rahul_membership,
        rahul_acme_grant=rahul_acme_grant,
        inactive_member=inactive_member,
        inactive_membership=inactive_membership,
        alice=alice,
        alice_membership=alice_membership,
        alice_apollo_grant=alice_apollo_grant,
        alice_acme_grant=alice_acme_grant,
        carol=carol,
        carol_membership=carol_membership,
        carol_apollo_grant=carol_apollo_grant,
        firm_b=firm_b,
        northstar_retail=northstar_retail,
        bob=bob,
        bob_membership=bob_membership,
        bob_northstar_grant=bob_northstar_grant,
        firm_b_admin=firm_b_admin,
        firm_b_admin_membership=firm_b_admin_membership,
    )
