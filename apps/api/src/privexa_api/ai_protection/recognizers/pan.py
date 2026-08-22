from __future__ import annotations

from presidio_analyzer import Pattern, PatternRecognizer

from privexa_api.ai_protection.profiles import INDIA_PAN


class IndiaPanRecognizer(PatternRecognizer):
    """Recognize the statutory PAN shape, including the holder-type position."""

    def __init__(self) -> None:
        super().__init__(
            supported_entity=INDIA_PAN,
            name="Privexa India PAN Recognizer",
            patterns=[
                Pattern(
                    name="Indian Permanent Account Number",
                    regex=r"\b[A-Z]{3}[ABCFGHJLPT][A-Z][0-9]{4}[A-Z]\b",
                    score=0.65,
                )
            ],
            context=["pan", "permanent account number", "income tax"],
            supported_language="en",
            version="1.0.0",
        )
