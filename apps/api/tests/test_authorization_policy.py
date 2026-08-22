from __future__ import annotations

from uuid import uuid4

import pytest

from privexa_api.access_control.context import FirmAuthorizationContext, FirmContext
from privexa_api.access_control.decisions import AuthorizationFailureReason
from privexa_api.access_control.enums import FirmRole
from privexa_api.access_control.errors import AuthorizationDeniedError
from privexa_api.access_control.permissions import AuthorizationScope, Permission
from privexa_api.access_control.policy import ROLE_PERMISSIONS, AuthorizationPolicy

EXPECTED_ROLE_PERMISSIONS = {
    FirmRole.FIRM_OWNER: frozenset(Permission),
    FirmRole.FIRM_ADMIN: frozenset(Permission) - {Permission.FIRM_OWNERS_MANAGE},
    FirmRole.CONSULTANT: frozenset(
        {
            Permission.FIRM_READ,
            Permission.CLIENT_READ,
            Permission.PROFILE_READ_SELF,
            Permission.PROFILE_UPDATE_SELF,
            Permission.FILE_CREATE,
            Permission.FILE_READ,
            Permission.FILE_DELETE,
            Permission.QUESTION_CREATE,
            Permission.QUESTION_READ,
            Permission.QUESTION_UPDATE,
        }
    ),
    FirmRole.REVIEWER: frozenset(
        {
            Permission.FIRM_READ,
            Permission.CLIENT_READ,
            Permission.PROFILE_READ_SELF,
            Permission.PROFILE_UPDATE_SELF,
            Permission.FILE_READ,
            Permission.QUESTION_READ,
        }
    ),
    FirmRole.READ_ONLY: frozenset(
        {
            Permission.FIRM_READ,
            Permission.CLIENT_READ,
            Permission.PROFILE_READ_SELF,
            Permission.PROFILE_UPDATE_SELF,
            Permission.FILE_READ,
            Permission.QUESTION_READ,
        }
    ),
}


def test_role_permission_mapping_exactly_matches_approved_matrix() -> None:
    assert dict(ROLE_PERMISSIONS) == EXPECTED_ROLE_PERMISSIONS


@pytest.mark.parametrize(
    ("role", "permission"),
    [(role, permission) for role in FirmRole for permission in Permission],
)
def test_complete_role_permission_matrix(role: FirmRole, permission: Permission) -> None:
    scope = {
        Permission.FIRM_READ: AuthorizationScope.FIRM,
        Permission.FIRM_UPDATE: AuthorizationScope.FIRM,
        Permission.FIRM_MEMBERS_READ: AuthorizationScope.FIRM,
        Permission.FIRM_MEMBERS_MANAGE: AuthorizationScope.FIRM,
        Permission.FIRM_OWNERS_MANAGE: AuthorizationScope.FIRM,
        Permission.CLIENT_CREATE: AuthorizationScope.FIRM,
        Permission.CLIENT_READ: AuthorizationScope.CLIENT,
        Permission.CLIENT_UPDATE: AuthorizationScope.CLIENT,
        Permission.CLIENT_ARCHIVE: AuthorizationScope.CLIENT,
        Permission.CLIENT_ASSIGNMENTS_READ: AuthorizationScope.CLIENT,
        Permission.CLIENT_ASSIGNMENTS_MANAGE: AuthorizationScope.CLIENT,
        Permission.FILE_CREATE: AuthorizationScope.CLIENT,
        Permission.FILE_READ: AuthorizationScope.CLIENT,
        Permission.FILE_DELETE: AuthorizationScope.CLIENT,
        Permission.QUESTION_CREATE: AuthorizationScope.CLIENT,
        Permission.QUESTION_READ: AuthorizationScope.CLIENT,
        Permission.QUESTION_UPDATE: AuthorizationScope.CLIENT,
        Permission.PROFILE_READ_SELF: AuthorizationScope.SELF,
        Permission.PROFILE_UPDATE_SELF: AuthorizationScope.SELF,
    }[permission]

    decision = AuthorizationPolicy.evaluate(
        role=role,
        permission=permission,
        required_scope=scope,
    )

    assert decision.allowed is (permission in EXPECTED_ROLE_PERMISSIONS[role])


@pytest.mark.parametrize("role", list(FirmRole))
def test_every_role_can_read_its_active_firm(role: FirmRole) -> None:
    decision = AuthorizationPolicy.evaluate(
        role=role,
        permission=Permission.FIRM_READ,
        required_scope=AuthorizationScope.FIRM,
    )

    assert decision.allowed is True
    assert decision.reason is None


@pytest.mark.parametrize("role", [FirmRole.FIRM_OWNER, FirmRole.FIRM_ADMIN])
def test_administrative_roles_receive_client_administration_permissions(
    role: FirmRole,
) -> None:
    for permission in (
        Permission.CLIENT_CREATE,
        Permission.CLIENT_UPDATE,
        Permission.CLIENT_ARCHIVE,
        Permission.CLIENT_ASSIGNMENTS_MANAGE,
    ):
        required_scope = (
            AuthorizationScope.FIRM
            if permission == Permission.CLIENT_CREATE
            else AuthorizationScope.CLIENT
        )
        decision = AuthorizationPolicy.evaluate(
            role=role,
            permission=permission,
            required_scope=required_scope,
        )
        assert decision.allowed is True


def test_only_owner_can_manage_firm_owners() -> None:
    owner = AuthorizationPolicy.evaluate(
        role=FirmRole.FIRM_OWNER,
        permission=Permission.FIRM_OWNERS_MANAGE,
        required_scope=AuthorizationScope.FIRM,
    )
    admin = AuthorizationPolicy.evaluate(
        role=FirmRole.FIRM_ADMIN,
        permission=Permission.FIRM_OWNERS_MANAGE,
        required_scope=AuthorizationScope.FIRM,
    )

    assert owner.allowed is True
    assert admin.allowed is False
    assert admin.reason == AuthorizationFailureReason.PERMISSION_DENIED


@pytest.mark.parametrize(
    "role",
    [FirmRole.CONSULTANT, FirmRole.REVIEWER, FirmRole.READ_ONLY],
)
def test_non_administrative_roles_cannot_manage_members(role: FirmRole) -> None:
    decision = AuthorizationPolicy.evaluate(
        role=role,
        permission=Permission.FIRM_MEMBERS_MANAGE,
        required_scope=AuthorizationScope.FIRM,
    )

    assert decision.allowed is False
    assert decision.reason == AuthorizationFailureReason.PERMISSION_DENIED


def test_scope_mismatch_denies_even_when_role_has_permission() -> None:
    decision = AuthorizationPolicy.evaluate(
        role=FirmRole.FIRM_OWNER,
        permission=Permission.CLIENT_READ,
        required_scope=AuthorizationScope.FIRM,
    )

    assert decision.allowed is False
    assert decision.reason == AuthorizationFailureReason.INVALID_CONTEXT


def test_unknown_role_has_no_permissions() -> None:
    decision = AuthorizationPolicy.evaluate(
        role="UNEXPECTED_ROLE",  # type: ignore[arg-type]
        permission=Permission.CLIENT_READ,
        required_scope=AuthorizationScope.CLIENT,
    )

    assert decision.allowed is False
    assert decision.reason == AuthorizationFailureReason.UNKNOWN_ROLE


def test_unknown_permission_never_implies_allow() -> None:
    decision = AuthorizationPolicy.evaluate(
        role=FirmRole.FIRM_OWNER,
        permission="client.reaad",  # type: ignore[arg-type]
        required_scope=AuthorizationScope.CLIENT,
    )

    assert decision.allowed is False
    assert decision.reason == AuthorizationFailureReason.UNKNOWN_PERMISSION


def test_authorization_context_cannot_be_constructed_without_validation_token() -> None:
    firm_context = FirmContext(
        user_id=uuid4(),
        membership_id=uuid4(),
        firm_id=uuid4(),
        role=FirmRole.FIRM_OWNER,
    )

    with pytest.raises(TypeError, match="AccessControlService"):
        FirmAuthorizationContext(
            _validation_token=object(),
            firm_context=firm_context,
            granted_permission=Permission.FIRM_READ,
        )


@pytest.mark.parametrize("malformed_context", [None, object()])
def test_missing_or_malformed_context_fails_with_controlled_denial(
    malformed_context: object | None,
) -> None:
    with pytest.raises(AuthorizationDeniedError) as captured:
        AuthorizationPolicy.require(
            malformed_context,  # type: ignore[arg-type]
            Permission.CLIENT_READ,
        )

    assert captured.value.reason == AuthorizationFailureReason.INVALID_CONTEXT


def test_missing_or_unknown_required_permission_fails_with_controlled_denial() -> None:
    with pytest.raises(AuthorizationDeniedError) as captured:
        AuthorizationPolicy.require(None, "client.reaad")  # type: ignore[arg-type]

    assert captured.value.reason == AuthorizationFailureReason.INVALID_CONTEXT
    assert captured.value.permission is None
