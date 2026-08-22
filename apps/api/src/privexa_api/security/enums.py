from enum import StrEnum


class SensitivityLevel(StrEnum):
    """Information-handling classification carried through protected processing."""

    STANDARD = "STANDARD"
    SENSITIVE = "SENSITIVE"
    RESTRICTED = "RESTRICTED"

    @property
    def severity(self) -> int:
        """Return the explicit policy rank; enum names and declaration order are irrelevant."""

        return {
            SensitivityLevel.STANDARD: 10,
            SensitivityLevel.SENSITIVE: 20,
            SensitivityLevel.RESTRICTED: 30,
        }[self]


class OriginatingChannel(StrEnum):
    """Trusted application entry point that established the execution."""

    WEB = "WEB"
