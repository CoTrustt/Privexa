from __future__ import annotations

from enum import StrEnum


class AuthorizationScope(StrEnum):
    FIRM = "FIRM"
    CLIENT = "CLIENT"
    SELF = "SELF"


class Permission(StrEnum):
    FIRM_READ = "firm.read"
    FIRM_UPDATE = "firm.update"
    FIRM_MEMBERS_READ = "firm.members.read"
    FIRM_MEMBERS_MANAGE = "firm.members.manage"
    FIRM_OWNERS_MANAGE = "firm.owners.manage"

    CLIENT_CREATE = "client.create"
    CLIENT_READ = "client.read"
    CLIENT_UPDATE = "client.update"
    CLIENT_ARCHIVE = "client.archive"
    CLIENT_ASSIGNMENTS_READ = "client.assignments.read"
    CLIENT_ASSIGNMENTS_MANAGE = "client.assignments.manage"

    FILE_CREATE = "file.create"
    FILE_READ = "file.read"
    FILE_DELETE = "file.delete"

    QUESTION_CREATE = "question.create"
    QUESTION_READ = "question.read"
    QUESTION_UPDATE = "question.update"

    PROFILE_READ_SELF = "profile.read_self"
    PROFILE_UPDATE_SELF = "profile.update_self"


_PERMISSION_SCOPES: dict[Permission, AuthorizationScope] = {
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
}


def permission_scope(permission: Permission) -> AuthorizationScope | None:
    """Return no scope for unknown input so policy evaluation fails closed."""

    return _PERMISSION_SCOPES.get(permission)
