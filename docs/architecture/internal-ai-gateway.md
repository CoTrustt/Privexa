# Internal AI Gateway

PBI-0.10 establishes `privexa_api.ai_gateway` as Privexa's only application-level model execution
boundary. It is an in-process module of the FastAPI modular monolith, not a separate service.

```text
Privexa capability
  -> AIExecutionRequest + trusted ExecutionContext
  -> task registry
  -> declared-source exact-set authorization under RLS
  -> deterministic AI Policy Engine
  -> immutable execution envelope
  -> policy-constrained model alias routing
  -> provider protocol
  -> OpenRouter adapter
  -> registered Pydantic output validation
  -> normalized AIExecutionResult and metadata-only telemetry
```

## Boundary rules

- Callers request a stable `AITaskType`; they do not supply a model, provider, system prompt, or
  output schema.
- Every call requires an `ExecutionContext` issued by Privexa's normal authorization path. Tenant
  identity in task input is data, never authority.
- The context is control-plane input. Firm/client IDs, roles, permissions, storage locations, and
  credentials are not sent to the provider.
- Task instructions are trusted Privexa content. Task/source text remains a separate untrusted user
  message.
- OpenRouter credentials and wire semantics exist only in the provider adapter and composition
  path.
- Provider adapters receive only explicitly authorized material. They cannot resolve source
  references or browse client storage.
- Raw prompts, source content, responses, authorization headers, and provider bodies are not logged
  or persisted.

Source IDs have zero authority. A task must declare an allowlist of source types, and every declared
type must have a registered deterministic resolver. A request may declare at most 100 sources. The
central authorizer verifies that its Session is bound to the same trusted execution context before
delegating to any resolver, then groups requested references, requires each resolver's typed
Permission, and requires the resolved IDs to exactly equal the requested IDs. The current production
resolver supports available `stored_file` records through Firm/Client-filtered queries and forced
RLS. The customer-facing `ai.prepare_work_note` task enables that source type and receives only
opaque, explicitly selected file IDs; source IDs are provenance and authorization inputs, not file
contents or permission grants.

Missing, duplicate, unknown, mixed-client, or otherwise unavailable sources reject the entire AI
execution before input content is protected, policy routing is evaluated, a prompt is constructed,
or a provider is called. Provenance starts with zero source rows for a rejected unverified set and
records only the safe normalized outcome. Telemetry records the reason code and counts, never raw
source content or attempted IDs.

## Build 0 policy

The infrastructure task `synthetic_text_summary` version `1` requires client scope, `client.read`,
no source references, and an explicit `STANDARD` task policy. The customer task
`ai.prepare_work_note` version `1` requires client scope and `file.read`, runs at `SENSITIVE`, and
allows up to 100 unique `stored_file` references. Unavailable or mixed-client references reject the
whole execution before provider I/O. Output sensitivity is derived through the existing
`SensitivityPolicy` and cannot be lower than input.

`AI_GATEWAY_ENABLED=false` is the central default. Disabled execution returns a normalized rejection
without constructing provider traffic. When enabled, startup requires a secret API key, one
configured synthetic-summary model, and explicit membership of that model in the approved list.

The Policy Engine returns provider/model classes, ZDR/redaction requirements, a source-controlled
protection profile, input/output token limits, timeout, per-request cost ceiling, fallback, and agent
authorities. When selected, the profile is executed against model-visible user content before route
resolution and provider-neutral request construction. The router must then prove a configured route
satisfies the policy envelope. The OpenRouter adapter denies data collection, enforces
the ZDR control, disables provider fallback, and applies operator-configured unit-price ceilings.
The Gateway rejects requests whose conservative worst-case cost exceeds policy. No automatic retry
occurs. Missing usage is absent rather than invented; reported cost is not customer billing.

See `ai-policy-engine.md` for precedence, tenant overrides, runtime switches, and versioning.

## Extension rules

A new capability adds typed input/output models and one versioned task definition. It reuses policy,
routing, provider execution, telemetry, timeout handling, and normalized errors. A new provider adds
an adapter behind the existing protocol. Feature code and future agents must not receive provider
credentials or call provider endpoints directly.

PII detection is implemented behind `privexa_api.ai_protection`; feature code and provider adapters
must not use Presidio directly. Detection components are built once with the Gateway, while token
mappings and raw-value transformation state exist only within one protection operation. Mandatory
protection failures reject execution and never fall back to the original content.

PBI-0.13 connects this centralized boundary to durable, tenant-scoped execution provenance. The
Gateway automatically records the logical execution, governed lifecycle events, source identifiers,
provider attempts, safe usage/cost metadata, trace correlation, and a canonical output hash. Feature
code does not write provenance itself. See `ai-execution-provenance.md` for persistence, privacy, and
failure semantics.
