# Tenant Security Gate

PBI-0.5 is Privexa's permanent adversarial regression gate for Firm and Client isolation. It proves
both that authorized work remains usable and that possession of a foreign identifier does not grant
authority.

## Security contract

The gate preserves three independent outcomes:

```text
authorized principal + authorized resource = allow
authorized principal + foreign resource = deny
missing application tenant filter + PostgreSQL RLS = authorized rows only
```

Authentication is not authorization. Stytch authenticates an opaque session, Privexa resolves the
current local FirmMembership, `AccessControlService` issues an action-bound context, and the
non-owner PostgreSQL runtime role remains constrained by forced RLS.

## Test database roles

- `TEST_DATABASE_URL` is the schema-owner connection. Tests use it only for Alembic migrations,
  deterministic fixture setup, lifecycle changes that simulate external administration, and final
  database-state verification.
- `TEST_APP_DATABASE_URL` is the application runtime connection. Every RLS and tenant-behavior
  assertion uses this role.
- The runtime role must not be a superuser, own protected tables, or hold `BYPASSRLS`.
- The test harness refuses destructive setup unless the database name ends in `_test`.

PostgreSQL settings are transaction-local: `privexa.user_id`, `privexa.membership_id`,
`privexa.firm_id`, and `privexa.client_id`. A SQLAlchemy Session must not switch actors, Firms, or
Clients.

## Running the gate

From `apps/api`, with the repository PostgreSQL 17 container running and test URLs loaded:

```bash
uv run pytest -m tenant_isolation
```

The GitHub Actions check is named `tenant-security-gate`. Repository branch protection must require
that check; the workflow deliberately does not use `continue-on-error`.

## AI and agent boundary

PBI-0.5 does not introduce production AI. Tests model two separate inputs:

- trusted Privexa execution context: authenticated principal plus intended Firm and Client;
- untrusted model or agent output: tool name and object identifier.

The mock executor calls `AccessControlService`, establishes the normal transaction-local database
scope, and performs the object lookup through the runtime Session. It has no owner connection,
special role, tenant-setting shortcut, or cached authorization. The agent simulation stores no live
Session and reauthorizes when execution begins, so membership and assignment revocations take
effect before a queued action runs.

## Extending the gate

When adding a protected route or tenant-bound table:

1. add it to the production and test protected-resource inventories;
2. add a same-tenant positive control;
3. attack a known same-Firm unassigned ID and a known cross-Firm ID where applicable;
4. test every supported read/write/relationship operation;
5. issue an intentionally unfiltered runtime query to prove RLS isolation;
6. test missing context and verify denied writes leave state unchanged;
7. test collection counts, filters, search, or bulk inputs only when those interfaces exist;
8. add the tests to the `security` and `tenant_isolation` markers.

Do not add fake production resources or endpoints merely to satisfy a checklist. Mark unsupported
attack categories as not applicable until the corresponding product surface exists.

## Determinism

The fixtures use nonempty, distinguishable Firms, Clients, memberships, and grants. Pool tests force
reuse of one physical connection, and concurrency tests use explicit barriers instead of sleeps.
The current fixture resets a shared PostgreSQL database per test, so the gate must not use
pytest-xdist without first introducing isolated databases per worker.
