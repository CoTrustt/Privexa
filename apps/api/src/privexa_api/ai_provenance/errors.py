class AIProvenanceError(Exception):
    """Safe boundary error for mandatory provenance persistence failures."""

    def __init__(self) -> None:
        super().__init__("AI provenance could not be persisted safely")


class AIProvenanceConflict(AIProvenanceError):
    """The same execution or event identity was reused with different facts."""
