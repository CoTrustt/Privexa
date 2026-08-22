from __future__ import annotations

from sqlalchemy.orm import Session

from privexa_api.access_control.errors import AuthorizationProblem
from privexa_api.ai_policy.contracts import (
    AIPolicyDecision,
    AIPolicyEvaluationRequest,
    AIPolicyRuntimeSnapshot,
)
from privexa_api.ai_policy.errors import InvalidAIPolicyConfiguration
from privexa_api.ai_policy.evaluator import AIPolicyEvaluator
from privexa_api.ai_policy.repository import AIPolicySnapshotRepository
from privexa_api.ai_policy.telemetry import AIPolicyTelemetry
from privexa_api.ai_types import AITaskType
from privexa_api.security.execution_context import require_trusted_execution_context


class AIPolicyEngine:
    def __init__(
        self,
        *,
        evaluator: AIPolicyEvaluator,
        repository: AIPolicySnapshotRepository,
        deployment_enabled: bool,
        telemetry: AIPolicyTelemetry | None = None,
    ) -> None:
        self._evaluator = evaluator
        self._repository = repository
        self._deployment_enabled = deployment_enabled
        self._telemetry = telemetry or AIPolicyTelemetry()

    def evaluate(
        self,
        *,
        session: Session | None,
        request: AIPolicyEvaluationRequest,
    ) -> AIPolicyDecision:
        started = self._telemetry.start()
        try:
            require_trusted_execution_context(request.context)
            if not isinstance(request.task, AITaskType):
                runtime = AIPolicyRuntimeSnapshot(global_enabled=True, task_enabled=True)
            elif not self._deployment_enabled:
                runtime = AIPolicyRuntimeSnapshot(
                    global_enabled=False,
                    task_enabled=True,
                )
            else:
                runtime = self._repository.load(
                    session,
                    context=request.context,
                    task=request.task,
                    sensitivity=request.context.effective_sensitivity,
                )
            decision = self._evaluator.evaluate(request=request, runtime=runtime)
        except (AuthorizationProblem, InvalidAIPolicyConfiguration, ValueError):
            decision = self._evaluator.configuration_denied(request)
        self._telemetry.evaluated(decision, started_clock=started)
        return decision

    def validate_startup(self, session: Session) -> None:
        if not self._deployment_enabled:
            return
        self._repository.validate_startup(
            session,
            registered_tasks=self._evaluator.registered_tasks,
        )
