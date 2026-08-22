# AI Availability Control

PBI-0.16 extends the internal AI Gateway so AI can stop without interrupting ordinary Privexa
work. The browser presents capability state, but the Gateway remains the only authority for model
execution.

```text
Feature or bounded agent step
  -> AI Gateway
  -> trusted ExecutionContext and source authorization
  -> global and task controls
  -> tenant, sensitivity, authority, and budget policy
  -> approved route
  -> provider administrative control
  -> provider/model circuit
  -> authority recheck
  -> provider adapter
  -> output validation
  -> authority and provider-control acceptance recheck
  -> provenance finalization
```

## Control precedence

`AI_GATEWAY_ENABLED=false` is the deployment ceiling. When it is enabled, the current revisioned
rows in `ai_policy_runtime_controls` govern the global switch and registered task switches. The
current revisioned rows in `ai_provider_runtime_controls` govern provider administrative
enablement. Missing, ambiguous, or hash-invalid control state fails closed for AI only.

The emergency order is global, task, normal AI policy, budget, provider administrative state, then
operational circuit state. Availability can remove an execution route; it cannot add a route or
relax tenant, sensitivity, ZDR, redaction, authority, or cost rules.

The runtime API role can read operator controls but cannot mutate them. An operator with the schema
owner connection can make one revisioned change with:

```bash
cd apps/api
set -a && source ../../.env && set +a
uv run python -m privexa_api.operations.ai_controls global disable
uv run python -m privexa_api.operations.ai_controls task ai.prepare_work_note disable
uv run python -m privexa_api.operations.ai_controls provider OPENROUTER disable
```

Use `enable` to restore a control. Repeating the current state is idempotent. The rows preserve
revision and effective/superseded times. Actor-attributed platform audit for operator commands is a
future operational-audit enhancement; no consultant-facing mutation endpoint or admin application
is introduced here.

## Environment verification and rollback drill

Before enabling AI in staging or production, an operator must capture a fresh read-only snapshot
from that environment's owner connection:

```bash
cd apps/api
set -a && source /path/to/environment.env && set +a
uv run python -m privexa_api.operations.ai_controls status
```

The release evidence must identify the intended environment, deployment ceiling, and provider mode;
show exactly one current global row and one current row for every registered task and provider;
show `configuration_valid=true` for each control; and show the expected provider/model circuit
state. This command emits operational IDs and counters only; it does not emit credentials, tenant
identifiers, prompts, or source content. Staging and production evidence must be captured
separately—one environment never proves the other.

The release owner must also record the named AI on-call owner, the alert destinations for provider
failures, timeouts, open circuits, and authority-revoked results, plus the rollback approver. Before
go-live and at least quarterly, drill this sequence in staging: disable the task, prove capability
and execution fail closed with zero provider attempts, re-enable it, disable the provider, prove the
same zero-cost behavior, restore it, and confirm a bounded smoke request succeeds. The global switch
is the production emergency rollback; the task and provider switches are narrower rollback options.
Do not declare production readiness from repository tests alone.

## Circuit behaviour

PostgreSQL stores circuit state at both provider and provider-model scope, so API instances share
health observations. Updates use short transactions and row locks. The default transition policy
is:

- five qualifying failures in 60 seconds opens the circuit;
- an open circuit blocks calls for 30 seconds and returns a bounded retry interval;
- one leased half-open probe is allowed cluster-wide;
- two successful half-open probes close the circuit;
- a failed half-open probe opens it again.

Timeouts, network/upstream unavailability, rate limits, invalid upstream responses, and invalid
structured output qualify. Global/task/policy/budget/provider-administrative denials and malformed
local requests do not. State contains operational identifiers and counters only—never prompts,
source content, output, user IDs, Firm IDs, or Client IDs. No paid health prompts are sent.

Settings can tune the defaults with `AI_CIRCUIT_FAILURE_THRESHOLD`,
`AI_CIRCUIT_FAILURE_WINDOW_SECONDS`, `AI_CIRCUIT_OPEN_SECONDS`,
`AI_CIRCUIT_HALF_OPEN_SUCCESS_THRESHOLD`, and `AI_CIRCUIT_PROBE_LEASE_SECONDS`.

## Retry, fallback, and in-flight semantics

Build 0 policy remains `NO_FALLBACK` and the Gateway performs zero automatic retries. This is a
bounded policy, not an implicit retry loop. Any future policy-approved attempt must re-run global,
task, provider, circuit, security, sensitivity, and budget checks before provider I/O.

An invocation that has not reached the provider is blocked immediately. The current HTTP adapter
does not claim cluster-wide cancellation of an already in-flight provider request. After a response
arrives, the Gateway re-evaluates global/task/policy authority and provider administrative state.
If authority changed, the validated provider result is discarded, no deterministic business state
is changed, and provenance records `RESULT_AUTHORITY_REVOKED`. The provider attempt and any actual
usage remain recorded accurately.

Every production model reasoning step, including a future agent step, must call `AIGateway.execute`
and therefore receives the same checks. There is no production agent runner or model-directed
mutating tool executor in Build 0. Deterministic retrieval already in progress may finish, but it
cannot grant a later model step authority.

## Capability and customer experience

`GET /v1/ai/tasks/ai.prepare_work_note/capability` returns only `AVAILABLE`,
`TEMPORARILY_UNAVAILABLE`, `UNAVAILABLE`, or `RESTRICTED`, plus bounded retry guidance. It does not
return provider, model, circuit threshold, or upstream diagnostics and creates no execution
provenance merely because the state was viewed.

The web client fetches this state once when the AI interaction mounts and refreshes its local state
after an execution response. It does not poll. A stale `AVAILABLE` response is never authority; the
backend rechecks on click. Only the AI action becomes unavailable. The textarea, manual edits,
navigation, client switching, and normal APIs remain independent of this control.

## Provenance and observability

Meaningful blocked attempts use the existing tenant-scoped provenance record. A pre-provider block
has zero provider attempts and no model cost. Availability and interruption categories are stored
without raw prompt or output. Read-only capability checks are not persisted.

Logs and OpenTelemetry spans add bounded task, availability, failure, provider-class, and circuit
state fields. OpenTelemetry counters cover Gateway outcomes, blocked calls, provider failures,
timeouts, open circuits, and authority-revoked results. No metric labels contain user, Firm,
Client, execution, document, or prompt identifiers. Intentional disablement is a normal product
condition and is not logged as an unexpected exception; Sentry is not currently installed.
