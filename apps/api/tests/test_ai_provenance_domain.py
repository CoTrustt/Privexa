from __future__ import annotations

import hashlib
from decimal import Decimal

import pytest
from pydantic import ValidationError

from privexa_api.ai_gateway.contracts import AIExecutionRequest, AITaskType, AIUsage
from privexa_api.ai_gateway.prompts import AIPromptRegistry, AIPromptTemplate
from privexa_api.ai_gateway.tasks import SyntheticTextSummaryInput, SyntheticTextSummaryResult
from privexa_api.ai_provenance.hashing import canonical_output_bytes, hash_output


def test_structured_output_hash_is_deterministic_and_content_sensitive() -> None:
    first = SyntheticTextSummaryResult(summary="same")
    same = SyntheticTextSummaryResult(summary="same")
    changed = SyntheticTextSummaryResult(summary="same.")

    assert hash_output(first) == hash_output(same)
    assert hash_output(first) != hash_output(changed)
    assert canonical_output_bytes(first).startswith(b"privexa-ai-output-v1\n")
    assert len(hash_output(first)) == 64


def test_prompt_identity_rejects_content_mutation_and_hides_instruction_from_repr() -> None:
    instruction = "SYSTEM_PROMPT_CANARY_102938"
    prompt = AIPromptTemplate(
        template_id="test",
        version="1",
        system_instruction=instruction,
        content_hash=hashlib.sha256(instruction.encode()).hexdigest(),
    )

    assert instruction not in repr(prompt)
    with pytest.raises(ValueError, match="content hash"):
        AIPromptTemplate(
            template_id="test",
            version="1",
            system_instruction=instruction + " changed",
            content_hash=prompt.content_hash,
        )
    with pytest.raises(ValueError, match="keys must match"):
        AIPromptRegistry({("test", "2"): prompt})


def test_sensitive_gateway_contract_repr_does_not_reveal_input() -> None:
    canary = "SENSITIVE_PROMPT_CANARY_928374"
    request = AIExecutionRequest(
        task=AITaskType.SYNTHETIC_TEXT_SUMMARY,
        input_data=SyntheticTextSummaryInput(text=canary),
    )

    assert canary not in repr(request)


def test_usage_distinguishes_unknown_from_zero_and_requires_iso_currency_shape() -> None:
    unknown = AIUsage()
    zero = AIUsage(reported_cost=Decimal("0"), cost_currency="USD")

    assert unknown.reported_cost is None
    assert zero.reported_cost == 0
    with pytest.raises(ValidationError):
        AIUsage(reported_cost=Decimal("0"), cost_currency="USDX")
    with pytest.raises(ValidationError, match="supplied together"):
        AIUsage(reported_cost=Decimal("0.1"))
    with pytest.raises(ValidationError, match="supplied together"):
        AIUsage(cost_currency="USD")
