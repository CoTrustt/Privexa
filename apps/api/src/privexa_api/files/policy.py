from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import PurePath
from urllib.parse import quote

from privexa_api.files.errors import FileValidationError

MIME_EXTENSION_POLICY: dict[str, frozenset[str]] = {
    "application/pdf": frozenset({".pdf"}),
    "text/plain": frozenset({".txt"}),
    "text/csv": frozenset({".csv"}),
    "image/png": frozenset({".png"}),
    "image/jpeg": frozenset({".jpg", ".jpeg"}),
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": frozenset({".docx"}),
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": frozenset({".xlsx"}),
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": frozenset(
        {".pptx"}
    ),
}

_SHA256_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")
_BIDI_CONTROL_CHARACTERS = frozenset(
    {
        "\u061c",
        "\u200e",
        "\u200f",
        "\u202a",
        "\u202b",
        "\u202c",
        "\u202d",
        "\u202e",
        "\u2066",
        "\u2067",
        "\u2068",
        "\u2069",
    }
)


@dataclass(frozen=True, slots=True)
class ValidatedFileMetadata:
    original_filename: str
    mime_type: str
    size_bytes: int
    checksum_sha256: str


def validate_file_metadata(
    *,
    original_filename: str,
    mime_type: str,
    size_bytes: int,
    checksum_sha256: str,
    max_size_bytes: int,
) -> ValidatedFileMetadata:
    filename = unicodedata.normalize("NFC", original_filename.strip())
    if not filename:
        raise FileValidationError(code="INVALID_FILENAME", detail="A filename is required.")
    if len(filename) > 255 or len(filename.encode("utf-8")) > 1024:
        raise FileValidationError(code="INVALID_FILENAME", detail="The filename is too long.")
    if "/" in filename or "\\" in filename:
        raise FileValidationError(
            code="INVALID_FILENAME",
            detail="The filename cannot contain path separators.",
        )
    if any(
        unicodedata.category(character) in {"Cc", "Cs"} or character in _BIDI_CONTROL_CHARACTERS
        for character in filename
    ):
        raise FileValidationError(
            code="INVALID_FILENAME",
            detail="The filename contains unsupported control characters.",
        )

    normalized_mime = mime_type.strip().lower()
    allowed_extensions = MIME_EXTENSION_POLICY.get(normalized_mime)
    if allowed_extensions is None:
        raise FileValidationError(
            code="UNSUPPORTED_FILE_TYPE",
            detail="This file type is not supported.",
        )
    extension = PurePath(filename).suffix.lower()
    if extension not in allowed_extensions:
        raise FileValidationError(
            code="FILE_TYPE_MISMATCH",
            detail="The filename extension does not match the declared file type.",
        )

    if size_bytes <= 0:
        raise FileValidationError(
            code="INVALID_FILE_SIZE",
            detail="The file must contain at least one byte.",
        )
    if size_bytes > max_size_bytes:
        raise FileValidationError(
            code="FILE_TOO_LARGE",
            detail="The file exceeds the configured upload limit.",
        )
    if not _SHA256_PATTERN.fullmatch(checksum_sha256):
        raise FileValidationError(
            code="INVALID_FILE_CHECKSUM",
            detail="A valid SHA-256 checksum is required.",
        )

    return ValidatedFileMetadata(
        original_filename=filename,
        mime_type=normalized_mime,
        size_bytes=size_bytes,
        checksum_sha256=checksum_sha256.lower(),
    )


def build_content_disposition(filename: str) -> str:
    ascii_fallback = "".join(
        character if character.isascii() and (character.isalnum() or character in " ._-") else "_"
        for character in filename
    ).strip()
    if not ascii_fallback:
        ascii_fallback = "download"
    ascii_fallback = ascii_fallback.replace("\\", "_").replace('"', "_")
    return f"attachment; filename=\"{ascii_fallback}\"; filename*=UTF-8''{quote(filename)}"
