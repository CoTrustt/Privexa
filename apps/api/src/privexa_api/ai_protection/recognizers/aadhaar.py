from __future__ import annotations

from presidio_analyzer import Pattern, PatternRecognizer

from privexa_api.ai_protection.profiles import INDIA_AADHAAR

_MULTIPLICATION = (
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9),
    (1, 2, 3, 4, 0, 6, 7, 8, 9, 5),
    (2, 3, 4, 0, 1, 7, 8, 9, 5, 6),
    (3, 4, 0, 1, 2, 8, 9, 5, 6, 7),
    (4, 0, 1, 2, 3, 9, 5, 6, 7, 8),
    (5, 9, 8, 7, 6, 0, 4, 3, 2, 1),
    (6, 5, 9, 8, 7, 1, 0, 4, 3, 2),
    (7, 6, 5, 9, 8, 2, 1, 0, 4, 3),
    (8, 7, 6, 5, 9, 3, 2, 1, 0, 4),
    (9, 8, 7, 6, 5, 4, 3, 2, 1, 0),
)
_PERMUTATION = (
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9),
    (1, 5, 7, 6, 2, 8, 3, 0, 9, 4),
    (5, 8, 0, 3, 7, 9, 6, 1, 4, 2),
    (8, 9, 1, 6, 0, 4, 3, 5, 2, 7),
    (9, 4, 5, 3, 1, 2, 6, 8, 7, 0),
    (4, 2, 8, 6, 5, 7, 3, 9, 0, 1),
    (2, 7, 9, 3, 8, 0, 6, 4, 1, 5),
    (7, 0, 4, 6, 9, 1, 3, 2, 5, 8),
)


def is_valid_aadhaar(value: str) -> bool:
    digits = value.replace(" ", "").replace("-", "")
    if (
        len(digits) != 12
        or not digits.isascii()
        or not digits.isdigit()
        or digits[0] in {"0", "1"}
        or digits == digits[::-1]
    ):
        return False
    checksum = 0
    for index, digit in enumerate(reversed(digits)):
        checksum = _MULTIPLICATION[checksum][_PERMUTATION[index % 8][int(digit)]]
    return checksum == 0


class IndiaAadhaarRecognizer(PatternRecognizer):
    def __init__(self) -> None:
        super().__init__(
            supported_entity=INDIA_AADHAAR,
            name="Privexa India Aadhaar Recognizer",
            patterns=[
                Pattern(
                    name="Aadhaar with optional separators",
                    regex=r"\b[2-9][0-9]{3}(?:[ -]?[0-9]{4}){2}\b",
                    score=0.45,
                )
            ],
            context=["aadhaar", "aadhar", "uidai", "unique identification"],
            supported_language="en",
            version="1.0.0",
        )

    def validate_result(self, pattern_text: str) -> bool:
        return is_valid_aadhaar(pattern_text)
