from __future__ import annotations

import json
from decimal import Decimal

from privexa_api.ai_gateway.contracts import AIFinishReason, AIUsage
from privexa_api.ai_gateway.providers.base import (
    AIProviderMetadata,
    AIProviderRequest,
    AIProviderResult,
)


class DeterministicAIProvider:
    """Network-free provider for local development and automated validation."""

    def __init__(self) -> None:
        self.invocation_count = 0

    async def execute(self, request: AIProviderRequest) -> AIProviderResult:
        self.invocation_count += 1
        if request.output_schema_name == "ai.prepare_work_note_v1":
            output = {
                "draft": (
                    "The client work note has been organised as a provisional summary for "
                    "professional review. The underlying facts and evidence still need to be "
                    "verified before any conclusion is recorded."
                ),
                "suggested_follow_up": (
                    "Confirm the stated facts with the client and link the supporting evidence."
                ),
                "caveat": "This draft is not a legal conclusion or a human decision.",
            }
        else:
            output = {"summary": "A concise synthetic summary."}
        return AIProviderResult(
            output_text=json.dumps(output, separators=(",", ":")),
            finish_reason=AIFinishReason.COMPLETED,
            usage=AIUsage(
                prompt_tokens=64,
                completion_tokens=48,
                total_tokens=112,
                reported_cost=Decimal("0"),
                cost_currency="USD",
            ),
            metadata=AIProviderMetadata(
                provider="DETERMINISTIC_LOCAL",
                adapter="DETERMINISTIC_TEST_V1",
                model=request.route.provider_model,
                request_id=f"deterministic-{self.invocation_count}",
            ),
        )

    async def aclose(self) -> None:
        return None
