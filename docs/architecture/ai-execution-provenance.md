# AI Execution Provenance

PBI-0.13 makes durable provenance a mandatory part of every governed AI Gateway execution. One
Gateway-generated UUID identifies the logical operation across policy evaluation, PII protection,
routing, provider attempts, logs, traces, persistence, and the returned result.

## Persistence shape

- `ai_executions` is the queryable summary and current terminal state.
- `ai_execution_events` is an ordered, append-only lifecycle. A provider retry or fallback is a new
  attempt event pair under the same logical execution, not a second customer execution.
- `ai_execution_sources` records authorized source type/ID references without copying source data.

The summary stores stable task and immutable prompt-template identities, the complete structured
policy outcome, aggregate PII entity classes/counts, selected and actual provider metadata,
usage/cost, timing, trace correlation, and terminal outcome. Events and source references have no
runtime UPDATE or DELETE grant. Summary updates are column-limited. All three tables use forced RLS
for the exact Firm and optional ClientWorkspace context established by the server.

## Privacy boundary

The provenance store never receives raw prompts, provider-visible transformed content, source text,
detected PII values, provider response bodies, or final model output. JSONB is limited to bounded
rule references, enum/count summaries, and safe event metadata. Logs and OpenTelemetry attributes
use the same metadata-only allowlist.

The successful output hash is SHA-256 over `privexa-ai-output-v1\n` followed by compact,
key-sorted UTF-8 JSON of the final validated Pydantic output. It supports later integrity comparison;
it does not prove factual correctness, provider honesty, human authorship, or that another copy was
never edited.

## Transaction and failure semantics

Provenance writes use short, independently committed transactions; no database transaction remains
open during provider I/O. If the initial record cannot be committed, the provider is not invoked. If
any later provenance write fails, the Gateway returns `PROVENANCE_UNAVAILABLE`; in particular, a
successful provider output is withheld unless terminal success and its output hash are durable.
Denied, preprocessing-failed, provider-failed, unexpected, and cancelled executions receive explicit
terminal states when persistence remains available.

The current Gateway performs one primary provider attempt and no automatic retry or fallback. The
event contract already distinguishes `PRIMARY`, `RETRY`, and `FALLBACK`, so future policy-approved
attempt logic can preserve per-attempt facts and aggregate usage/cost without overwriting earlier
failures.

## Tracing

The Gateway emits `ai.execution`, `ai.policy.evaluate`, `ai.protection.apply`, `ai.route.select`, and
`ai.provider.attempt` spans. Safe attributes include execution/attempt IDs, task ID, provider, and
model. The root trace/span IDs are stored on `ai_executions`; attempt span IDs are stored on their
events. Exporters and sampling remain deployment configuration.
