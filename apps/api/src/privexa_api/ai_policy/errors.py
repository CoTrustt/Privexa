from __future__ import annotations

from privexa_api.ai_policy.contracts import AIPolicyDecision, AIPolicyReasonCode


class AIPolicyDenied(Exception):
    def __init__(self, decision: AIPolicyDecision) -> None:
        super().__init__(decision.reason_code.value)
        self.decision = decision


class InvalidAIPolicyConfiguration(Exception):
    pass


class NoCompliantAIRoute(Exception):
    def __init__(self, reason_code: AIPolicyReasonCode) -> None:
        super().__init__(reason_code.value)
        self.reason_code = reason_code


class AIBudgetExceeded(NoCompliantAIRoute):
    def __init__(self) -> None:
        super().__init__(AIPolicyReasonCode.BUDGET_EXCEEDED)
