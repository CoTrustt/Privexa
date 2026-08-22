# Domain Object Kernel and Contracts

PBI 1.1 defines the deterministic substrate for Privexa professional objects such as Question,
ProcessingActivity, Evidence, Obligation, Decision, and Action. It does not implement those
aggregates and it has no dependency on the AI Gateway.

## Boundaries

Professional mutations follow one path:

```text
authenticated entry point
  -> AccessControlService and action-specific Permission
  -> trusted client-scoped ExecutionContext
  -> concrete application service
  -> professional-record authority and domain invariants
  -> SQLAlchemy repository/persistence operation
  -> PostgreSQL constraints and forced RLS
  -> in-process domain event and future audit hook
```

Routes, workers, scripts, and future agents must use the same path. They must not construct an
`ExecutionContext`, `ProfessionalRecordAuthority`, Firm ID, Client ID, creator, or updater from a
request body or serialized worker payload. A future worker must re-establish current authorization
and database scope before it calls an application service.

## Identity and ownership

Use `UUIDPrimaryKeyMixin` and keep UUIDv4 as Privexa's current non-guessable public identity
convention. Client-owned professional records physically store both `firm_id` and `client_id`.
`client_id` is the established implementation name for `ClientWorkspace.id`; renaming the Build 0
security context is outside this PBI.

Every concrete professional table must combine `ClientOwnedMixin`, `ActorProvenanceMixin`,
`VersionedMixin`, `TimestampMixin`, and `UUIDPrimaryKeyMixin`, then explicitly include
`professional_object_constraints(table_name, ...)` in its `__table_args__`. The resulting database
contract includes:

- a composite `(firm_id, client_id)` foreign key to
  `client_workspaces(firm_id, id)`;
- composite creator and updater foreign keys to
  `firm_memberships(firm_id, id)`;
- globally unique UUID identity plus a tenant-scoped `(firm_id, client_id, id)` key;
- a positive optimistic-concurrency version;
- ordered timezone-aware creation/update timestamps;
- a tenant/creation-time access index.

The concrete model must be passed to `validate_professional_object_model` during its module or model
registry tests. It must also be classified as `ResourceScope.CLIENT` in the existing resource-scope
registry. The validation helper is a guardrail; PostgreSQL constraints remain authoritative.

`ProfessionalRecordAuthority` is issued only from a trusted client-scoped `ExecutionContext` after
the caller's action-specific `Permission` succeeds. Issuance is explicitly bound to `CREATE`,
`UPDATE`, or `ARCHIVE`, and the final segment of the permission must match that operation (`create`,
`update`/`manage`, or `archive`). A read-only context cannot be converted into mutation authority,
and an authority issued for one mutation cannot be reused for another. Its
creation/update/archive values are therefore server-derived. Application services must also call
`require_matching_execution_context_scope(session, context)` before protected persistence so the
SQLAlchemy Session and authority envelope cannot diverge.

## RLS contract for future professional tables

Each concrete professional-object migration must use the existing Build 0 pattern:

1. Enable and force RLS.
2. Restrict `SELECT` with both `validated_firm_id()` and `validated_client_id()`.
3. Restrict `INSERT` with the same ownership checks and require creator/updater Membership IDs to
   equal `current_context_uuid('privexa.membership_id')`.
4. Restrict `UPDATE` with `USING` and `WITH CHECK`; ownership is immutable and the updater must be
   the current Membership.
5. Grant the runtime role only the mutation columns the application service implements.
6. Do not grant hard `DELETE` for an archivable professional work product unless a later retention
   design explicitly requires it.

RLS settings remain transaction-local through `set_config(..., true)`. A Session cannot switch Firm
or Client because its identity map can return cached rows without another SQL query. Multi-client
work uses one new transaction and Session per client. The runtime role must remain non-owner,
non-superuser, and without `BYPASSRLS`.

## Timestamps, versioning, and archival

`created_at` and `updated_at` are timezone-aware PostgreSQL timestamps. Creation values come from the
database; SQLAlchemy writes set `updated_at`. `created_at` is immutable through runtime column
grants.

`VersionedMixin` is opt-in for mutable professional objects and configures SQLAlchemy's integer
`version_id_col`, starting at one. Commands carry an explicit expected version. The authority helper
provides an early deterministic check, while SQLAlchemy's version predicate protects the race at
flush time. Both failures map to the safe `409 VERSION_CONFLICT` API contract. ETag/If-Match can be
added later without changing the persistence model.

Archival is also opt-in. `ArchivableMixin` stores `archived_at` with
`archived_by_membership_id`; both must be null or both present. Queries must state whether archived
records are included—there is no hidden ORM filter. Archival preserves professional work product and
is not the same as privacy erasure, retention expiry, or legal-hold processing.

## Lifecycle, errors, events, and audit

Each aggregate owns its own `StrEnum` states and `LifecyclePolicy`. There is no universal status enum.
Disallowed changes raise `LIFECYCLE_CONFLICT`.

Domain failures use stable, customer-safe codes and the existing Problem Details envelope. Cross-
tenant ownership mismatches are logged internally as `TENANT_OWNERSHIP_MISMATCH` but returned as the
generic `404 RESOURCE_NOT_FOUND`. PostgreSQL statements, constraint text, object contents, and stack
traces must never enter API responses.

FastAPI request validation uses `422 REQUEST_VALIDATION_FAILED` plus sanitized `field_errors`
containing only the request path and a bounded `REQUIRED`, `EXTRA_FIELD`, `INVALID_JSON`, or
`INVALID_VALUE` classification. Pydantic messages and rejected input values are not echoed because
they may contain client content.

`DomainEvent` is an immutable, JSON-safe, client-scoped in-process envelope. Events are collected in
`DomainEventCollector` and dispatched only by the application boundary after the authoritative
operation and database transaction succeed. The application boundary must call `discard()` after a
rollback; `drain()` is reserved for the post-commit path. A domain event is not an audit record and
is not yet a durable integration event. A future transactional outbox can serialize the same
envelope without placing broker logic inside domain objects.

Creator/updater columns describe current provenance. They do not replace append-oriented audit
history. Request ID, trace ID, actor IDs, originating channel, and event metadata provide hooks for a
later audit PBI without prematurely creating an audit subsystem.

## Observability and AI boundary

Use `domain_span` for application/domain operation spans. Attributes must be an explicit safe
allowlist: operation, object type, result category, request/trace correlation, and tenant IDs where
policy permits. Span names and allowed attribute values are validated as code identifiers, UUIDs,
trace IDs, or bounded result categories before emission. Never attach professional content,
evidence bodies, tokens, credentials, prompts, or serialized ORM objects.

The domain package imports no AI code. AI and future agent workflows may prepare commands and call
the same authenticated application services, but they cannot choose ownership, actor provenance,
versions, transaction boundaries, lifecycle outcomes, or RLS context. No agent database role or RLS
exception is permitted.

## Migration policy

PBI 1.1 introduces reusable Python contracts but no production aggregate table, so it intentionally
adds no empty or speculative Alembic revision. The current migration head remains `20260822_0018`.
The first downstream professional-object PBI must add a new migration containing its actual table,
constraints, indexes, grants, and RLS policies and must pass the empty-database migration gate.

The PBI 1.1 tests use a test-only representative mapped object and real PostgreSQL policies to prove
the contract, including composite ownership, missing and invalid context, raw and ORM unfiltered
reads, connection reuse after commit and rollback, forged actor values, bounded grants, hard-delete
denial, archival attribution, rollback event discard, and concurrent stale-write rejection.
