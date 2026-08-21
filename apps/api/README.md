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
`require_client_permission(Permission...)`, or `require_self_permission(Permission...)`, pass the
returned context into an application service, and let that service call a Firm/client-scoped
repository. Do not pass request `user_id` or `firm_id` values into authorization, construct
authorization contexts directly, or call protected repositories from routes.

RLS is enabled and forced on `firms`, `users`, `firm_memberships`, `client_workspaces`, and
`client_access_grants`. Missing or malformed context exposes no protected rows. The FastAPI process
also refuses to start if its database role is a superuser, has `BYPASSRLS`, owns a protected table,
or encounters a protected table without forced RLS. Alembic remains the only normal schema-owner
path; never configure `APP_DATABASE_URL` with `DATABASE_URL` credentials.

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

Run the complete API regression suite with:

```bash
uv run pytest
```

Every future protected table or route must extend the tenant-security inventory and add both an
authorized positive control and relevant foreign-tenant attacks. See
`docs/architecture/tenant-security-gate.md` for the permanent contract.
