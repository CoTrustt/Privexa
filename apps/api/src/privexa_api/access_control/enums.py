from enum import StrEnum


class FirmRole(StrEnum):
    FIRM_OWNER = "FIRM_OWNER"
    FIRM_ADMIN = "FIRM_ADMIN"
    CONSULTANT = "CONSULTANT"
    REVIEWER = "REVIEWER"
    READ_ONLY = "READ_ONLY"


class MembershipStatus(StrEnum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


class ClientAccessStatus(StrEnum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"
