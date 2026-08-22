# AI Policy Engine

PBI-0.11 establishes `privexa_api.ai_policy` as the deterministic governance boundary in front of
every normal AI Gateway provider invocation. The Gateway executes approved work; policy decides
whether that work is permitted and returns the immutable maximum execution envelope.

```text
Feature -> AI Gateway -> AI Policy Engine -> ALLOW/DENY
                                      ALLOW -> constrained route -> provider adapter
                                      DENY  -> no route and no provider call
```

## Policy inputs and trust

The Gateway builds the evaluation request from a server-issued `ExecutionContext`, the registered
task definition, and caller limits that can only tighten policy. Firm, ClientWorkspace, permission,
and effective sensitivity are never accepted from task payloads. Policy source references remain
metadata; policy neither reads files nor grants storage access.

`Firm` is the commercial tenant and `ClientWorkspace.id` is the canonical `client_id`. Database
overrides are queried through the same tenant-bound SQLAlchemy Session as the protected operation.
The runtime role has read-only access, and forced RLS admits Firm-wide rules plus rules for exactly
the current ClientWorkspace.

## Rules and precedence

The source-controlled `build0-v1` registry provides the global security ceiling, one rule for every
sensitivity, and explicit task/sensitivity rules. PostgreSQL supplies global/task runtime switches
and optional Firm/Client restrictions. Missing runtime controls, missing task rules, malformed
configuration, and empty class intersections deny execution.

Applicable layers constrain one another:

- provider and model class sets intersect;
- token, timeout, and monetary ceilings use the minimum;
- ZDR and redaction use the strictest requirement;
- protection profiles use the most restrictive registered profile;
- any disabled switch denies;
- fallback uses the most restrictive mode;
- agent authorities intersect explicit allowlists.

Tenant policy can therefore restrict but cannot expand the global ceiling.

## Build 0 execution envelope

The only registered task remains `synthetic_text_summary` version `1`, and it is explicitly allowed
only for `STANDARD` contexts. The configured route must be `ENTERPRISE_APPROVED` or `ZDR_APPROVED`,
use a `GENERAL_APPROVED` model class, support ZDR, disable fallback, remain within input/output token
limits, and fit the deterministic worst-case cost ceiling.

`SENSITIVE` and `RESTRICTED` baseline rules require redaction and restricted-data-approved routing.
They select the `EXTERNAL_MODEL_PII_V1` protection profile. Any future task allowed for those
sensitivities must complete that profile before route resolution and provider request construction;
missing or failed protection rejects execution.

Build 0 AI authority is limited to `READ_AUTHORISED_CONTEXT` and
`PREPARE_PROPOSED_OUTPUT`. These do not create data access or authoritative decisions. Mutation,
external communication, approval/sign-off, cross-client movement, destructive actions, and
permission changes are not grantable.

## Operational controls and versioning

`AI_GATEWAY_ENABLED` is a deployment safety ceiling. `ai_policy_runtime_controls` contains a global
switch and one switch per registered task; the migration seeds global AI disabled and the synthetic
task enabled. Both deployment and database controls must permit execution. Operations may change
these records through a separately privileged database path; there is no customer mutation API.

`ai_policy_overrides` stores revisioned restrictive JSONB overlays. Decisions record the baseline
version, effective rule IDs/revisions/hashes, a combined policy hash, and a deterministic decision
fingerprint. Structured logs contain policy and execution metadata only—never prompts, documents,
raw model output, storage locations, tokens, or credentials.

Build 0 performs no policy caching. This keeps emergency switches immediate and avoids stale or
cross-client results. A future cache must include Firm, ClientWorkspace, task, sensitivity, and all
policy-version dimensions in its key.
