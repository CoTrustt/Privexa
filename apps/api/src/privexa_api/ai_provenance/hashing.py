from __future__ import annotations

import hashlib
import json

from pydantic import BaseModel

OUTPUT_HASH_ALGORITHM = "SHA-256"
OUTPUT_CANONICALIZATION = "PRIVEXA_STRUCTURED_JSON_V1"
_DOMAIN_SEPARATOR = b"privexa-ai-output-v1\n"


def canonical_output_bytes(output: BaseModel) -> bytes:
    """Return the stable final Privexa response representation used for integrity comparison."""

    normalized = output.model_dump(mode="json", round_trip=True)
    encoded = json.dumps(
        normalized,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return _DOMAIN_SEPARATOR + encoded


def hash_output(output: BaseModel) -> str:
    """Hash the validated Privexa output, not raw provider text or prompt content."""

    return hashlib.sha256(canonical_output_bytes(output)).hexdigest()
