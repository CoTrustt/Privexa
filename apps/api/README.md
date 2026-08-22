# Privexa API

PBI-0.1 establishes the persistence and tenant-context foundation. PBI-0.2 adds the FastAPI
authentication boundary backed by Stytch B2B.

## Local database

1. Copy the repository `.env.example` to `.env` and replace the placeholder passwords.
2. Start PostgreSQL with `docker compose up -d postgres` from the repository root.
3. From `apps/api`, run `uv sync --dev` and `uv run alembic upgrade head` against
   `privexa_dev`.

Development and automated tests must use different databases:

```text
privexa_dev   local application and manual identities
privexa_test  Pytest fixtures only
```

Development startup rejects an `APP_DATABASE_URL` whose database name ends in `_test`. The Pytest
harness performs the inverse check before destructive fixture setup. A test run must never point at
the database used by the local application.

The Compose initialization creates separate schema-owner and runtime roles. Alembic uses the owner
connection from `DATABASE_URL`. Application code must use the non-owner runtime role so PostgreSQL
row-level security cannot be bypassed by table ownership.

## Professional domain object kernel

PBI 1.1 provides the reusable deterministic contracts for future Question, ProcessingActivity,
Evidence, Obligation, Decision, and Action records. It standardizes explicit client ownership,
Membership-derived provenance, optimistic versioning, opt-in archival, lifecycle validation, safe
domain errors, in-process domain events, and domain tracing without adding speculative production
tables. Adoption rules and the required PostgreSQL/RLS migration template are documented in
`docs/architecture/domain-object-kernel.md`.

## Tenant context

Only `AccessControlService.authorize_firm`, `AccessControlService.authorize_client`, and
`AccessControlService.authorize_self` should turn an authenticated principal and requested scope
into trusted authorization context. Authentication maps the exact Stytch Member/Organization pair
through a narrowly permissioned database function, then establishes Firm scope. Only a requested
Client ID is accepted as an untrusted claim. The service revalidates the current membership,
evaluates a typed Permission, sets a transaction-local candidate Client scope, and lets RLS verify
effective Client authorization before returning an action-bound context.

Database settings use `set_config(..., true)` and are local to the request transaction. A SQLAlchemy
`Session` may narrow from one Firm to one Client, but must never switch Firm or Client because its
identity map can return objects without issuing SQL. Multi-Client work must use a new Session per
Client. Future background workers must establish the same validated `FirmContext`/`ClientContext`;
they must not open a global application session.

`FIRM_OWNER` and `FIRM_ADMIN` memberships receive every active ClientWorkspace in their own Firm.
`CONSULTANT`, `REVIEWER`, and `READ_ONLY` memberships require an active ClientAccessGrant. All roles
remain restricted to the Firm identified by their Membership.

Future protected routes should use `require_firm_permission(Permission...)`,
`require_self_permission(Permission...)`, or one of the active-client dependencies. An ordinary
client resource route with a `{client_id}` path uses `require_active_client_path_permission(...)`;
the path value must match the server-selected active client. Only the active-client switch route may
use `require_switch_target_client_permission(...)` to authorize a new explicit target. Pass the
returned `ExecutionContext` into an application service and let that service derive the narrow
Firm/client context used by its repository. Do not pass request `user_id` or `firm_id` values into
authorization, construct execution contexts from request data, or call protected repositories from
routes. The authorization service remains responsible for deciding authority; the execution context
carries its action-bound result downstream.

Routes that operate on the user's currently selected workspace may use
`require_active_client_permission(Permission...)`. This dependency reads the active selection for
the validated Stytch member session, independently reauthorizes that ClientWorkspace, and issues a
new immutable client-scoped `ExecutionContext`. The browser never supplies the Firm, Membership,
role, or capabilities for this flow.

PBI-0.15 separates navigation from resource access. Switching clients validates the requested
target, while ordinary client-scoped operations are bound to the already active server session.
Having access to two clients does not authorize using one client's URL or resource IDs while the
other is active. The route inventory records this distinction as an explicit protection class.

Privexa generates the canonical request UUID even when a caller supplies `X-Request-ID`. The optional
trace ID remains separate and is unset until supported tracing infrastructure provides a valid active
trace. Current protected web execution begins with `STANDARD` effective sensitivity and originates
from the server-controlled `WEB` channel. Loading more sensitive information creates an immutable
derived context at `SENSITIVE` or `RESTRICTED`; downstream execution never becomes less restrictive.
See `docs/architecture/canonical-execution-context.md` and
`docs/architecture/data-sensitivity-policy.md` for field provenance and policy rules.

RLS is enabled and forced on `firms`, `users`, `firm_memberships`, `client_workspaces`,
`client_access_grants`, `stored_files`, and `active_client_sessions`. Missing or malformed context
exposes no protected rows. The FastAPI process also refuses to start if its database role is a
superuser, has `BYPASSRLS`, owns a protected table, or encounters a protected table without forced
RLS. Alembic remains the only normal schema-owner path; never configure `APP_DATABASE_URL` with
`DATABASE_URL` credentials.

Authorization responses use `401` for authentication failure, `403` for prohibited actions in a
valid visible scope, and a generic `404` for unavailable or cross-tenant scopes. Private decision
reasons are logged with the request ID and internal identifiers without tokens or client content.

## Authentication boundary

After copying the repository `.env.example` to `.env`, run the API from `apps/api` with
`uv run uvicorn privexa_api.asgi:app --reload --env-file ../../.env`. The runtime requires
`APP_DATABASE_URL`, `STYTCH_PROJECT_ID`, and `STYTCH_SECRET`.

`GET /v1/auth/session` authenticates the opaque `stytch_session` cookie with Stytch on every
request, then maps the returned organization/member pair to an active local FirmMembership.
`POST /v1/auth/logout` requires the configured web Origin, revokes the Stytch session, and expires
the auth cookies. Callers never supply trusted Firm or Membership IDs.

## Authenticated application context

`GET /v1/application-context` returns a narrow browser-safe projection of the authenticated user,
Firm, current active ClientWorkspace, and only the ClientWorkspaces currently authorised by the
existing access-control policy. It deliberately requires an explicit first selection instead of
deriving authority from list order.

`PUT /v1/application-context/active-client/{client_id}` treats the path value as an untrusted
request. The normal client authorization dependency validates it, then stores only the authorised
Client ID against a SHA-256 fingerprint of the validated Stytch member-session ID. Selection is
session-specific, RLS-protected, and revalidated when application context or a downstream active
client dependency is resolved. The switch does not mutate the current request's immutable
`ExecutionContext`; subsequent requests receive the new client scope.

For a local test identity, create one Stytch B2B organization and member, then link their IDs to
the corresponding existing Privexa records. Set `firms.stytch_organization_id` and
`firm_memberships.stytch_member_id`; do not create a second Privexa user or use a client workspace
as the Stytch organization. A valid Stytch session without those exact links is deliberately denied.

Use the development-only provisioning command instead of editing identity rows manually:

```bash
PRIVEXA_ENVIRONMENT=development \
DATABASE_URL='postgresql+psycopg://OWNER:...@localhost:5432/privexa_dev' \
python -m privexa_api.development.provision \
  --firm-name 'Privexa Local Test Firm' \
  --stytch-organization-id 'organization-test-...' \
  --email 'developer@example.com' \
  --display-name 'Developer' \
  --role FIRM_OWNER \
  --stytch-member-id 'member-test-...' \
  --client 'NxtGen Sandbox'
```

The command is idempotent, refuses non-development or `_test` databases, checks identity conflicts,
and may assign selected clients to consultant/reviewer/read-only memberships with
`--assign-client`.

## Tenant security gate

PBI-0.5 maintains an adversarial tenant-isolation suite against the real PostgreSQL runtime role.
Start the repository PostgreSQL container, load the test URLs from the repository `.env`, and run:

```bash
uv run pytest -m tenant_isolation
```

The marked suite covers authorization, known foreign identifiers, direct unfiltered queries,
write and relationship isolation, missing database context, transaction/pool cleanup, concurrent
tenant transactions, and mocked AI-tool and agent boundaries. It must never run through
`DATABASE_URL`; tenant assertions use `TEST_APP_DATABASE_URL`, while the owner connection is limited
to migrations, deterministic setup, lifecycle changes, and postcondition checks.

## Internal AI Gateway

PBI-0.10 adds a backend-only, task-oriented AI execution boundary. Product code imports the public
contracts from `privexa_api.ai_gateway` and invokes a registered task with an authoritative
`ExecutionContext`. It never supplies a provider, model, raw system prompt, tenant identifier, or
provider credential.

The infrastructure task `synthetic_text_summary` remains available for regression coverage. The
customer-facing Build-0 task is `ai.prepare_work_note` version `1`: it accepts a bounded work note,
requires trusted active-client `file.read` context, optionally accepts up to 100 unique stored-file
IDs, applies the sensitive-data protection profile, and returns a Pydantic-validated provisional
candidate. Every selected file is exact-set authorized as an available record in the active Firm
and ClientWorkspace before provider execution, and only authorized references are recorded in
provenance. The business endpoint is
`POST /v1/ai/tasks/ai.prepare_work_note/prepare`; it never mutates an authoritative record.

AI execution is disabled by default. `AI_PROVIDER_MODE=deterministic` enables a network-free
development/test provider and is rejected in staging/production. `AI_PROVIDER_MODE=openrouter`
uses the server-only `OPENROUTER_API_KEY` when present plus task models explicitly included in
`AI_APPROVED_OPENROUTER_MODELS`. A missing development credential does not prevent application
startup; live invocation returns a safe configuration failure. Test configuration rejects
OpenRouter mode so automated checks cannot consume paid inference. OpenRouter remains an internal
adapter detail. Logs contain only
execution, tenant, task, provider, timing, usage, cost, and normalized outcome metadata; prompts,
source content, provider response bodies, and credentials are excluded.

For a deterministic development demonstration, provision both synthetic clients with the existing
development-only command by passing `--client 'Apollo Finance Demo'`,
`--client 'Restricted Client Demo'`, and
`--restrict-work-note-ai-client 'Restricted Client Demo'` (plus assignments when using a scoped
role). This idempotently creates the restricted task override without customer data.

The gateway sends structured-output requests only to endpoints satisfying the task parameters,
denies provider data collection, requires Zero Data Retention, disables fallback, and applies
configured maximum per-million-token prices. Reported cost is operational telemetry, not billing.

PBI-0.11 places the deterministic `privexa_api.ai_policy` capability inside this path. Every normal
Gateway call receives an immutable ALLOW/DENY decision before routing. ALLOW carries provider/model
classes, ZDR/redaction requirements, a protection profile, token and cost ceilings, fallback, and
the Build 0 authority allowlist. When a profile is selected, the reusable Presidio-backed protection
service transforms model-visible user content before routing and provider request construction.
Request-local token maps are neither logged nor persisted, and mandatory failures reject execution.
PostgreSQL runtime controls and RLS-scoped Firm/Client overrides may only make execution more
restrictive. The migration seeds global AI disabled; enabling the deployment setting alone is not
sufficient until the operational control is explicitly enabled.

PBI-0.13 makes privacy-safe provenance automatic at the same Gateway boundary. Each governed call
creates one logical `ai_executions` record, ordered append-only lifecycle events, and source-ID
references under forced Firm/Client RLS. Provider attempts, safe PII aggregates, usage/cost, trace
correlation, and a canonical validated-output hash are recorded without persisting prompts, source
contents, detected values, response bodies, or outputs. Provenance failure is fail-closed: model I/O
does not begin without an initial record, and successful output is withheld unless finalization is
durable. See `docs/architecture/ai-execution-provenance.md`.

AI tasks that declare source types must resolve every source through a registered server-side
resolver under the execution's RLS-bound `ExecutionContext`. Mixed-client, missing, duplicate,
unknown, or unauthorized source sets fail atomically before policy routing, prompt construction, or
provider I/O. Rejected provenance contains the execution outcome and zero unverified source rows;
raw source content and foreign identifiers are not logged.

PBI-0.16 adds revisioned global, task, and provider controls plus shared PostgreSQL provider/model
circuit state. The Gateway rechecks authority immediately before provider I/O and again before
accepting a response, so a switch activated during an in-flight request causes the result to be
discarded safely. The browser receives only product-safe capability state and manual work remains
available. Build 0 keeps zero automatic retries and `NO_FALLBACK`. Operator commands, circuit
defaults, failure taxonomy, and local demonstrations are documented in
`docs/architecture/ai-availability-control.md`.

Run the complete API regression suite with:

```bash
uv run pytest
```

Every future protected table or route must extend the tenant-security inventory and add both an
authorized positive control and relevant foreign-tenant attacks. See
`docs/architecture/tenant-security-gate.md` for the permanent contract.
