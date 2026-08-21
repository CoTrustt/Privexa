# Tenant and Client Foundation

## Domain boundary

`Firm` is Privexa's commercial tenant. `ClientWorkspace` is the isolated workspace for a client
organisation managed by exactly one Firm; the product may call it a Client, and its `id` is the
canonical `client_id`.

```text
User
  └── FirmMembership ── Firm
          └── ClientAccessGrant ── ClientWorkspace
```

A User is global identity. Firm access, role, and lifecycle belong to `FirmMembership`, not User.
A Firm does not authenticate; a human User authenticates and acts through a FirmMembership so the
actor remains attributable. `FIRM_OWNER` and `FIRM_ADMIN` memberships receive all active
ClientWorkspaces owned by their Firm. `CONSULTANT`, `REVIEWER`, and `READ_ONLY` memberships require
an active `ClientAccessGrant` for each ClientWorkspace.

There is no separate Workspace or Organisation entity in Build 0. If a future legal-client entity
needs multiple isolated workspaces, it can be introduced above existing ClientWorkspaces without
changing their tenant identities.

## Ownership rule for future resources

Every client-private table must contain non-null `firm_id` and `client_id` columns. The pair must
reference the owning ClientWorkspace:

```text
(firm_id, client_id)
    → client_workspaces(firm_id, id)
```

This rule applies to future Evidence, Questions, Processing Activities, RoPA data, DPIAs, Opinions,
Decisions, Actions, AI conversations, agent runs, usage records, and client-scoped audit events.
Relationships between client-scoped resources must also include their tenant columns when needed to
prevent cross-client links.

Firm Knowledge carries `firm_id` without `client_id`. Platform Knowledge carries neither. A
tenant-owned audit event carries `firm_id`; `client_id` is present for a client-scoped event and may
be null only for a genuinely Firm-level event.

## Authorization and row-level security

An incoming `firm_id` or `client_id` is a request parameter, not trusted context.
`AccessControlService.authorize_firm`, `AccessControlService.authorize_client`, and
`AccessControlService.authorize_self` accept an `AuthenticatedPrincipal`, never caller-supplied
actor or Firm identifiers. They first confirm:

- active User;
- active Firm;
- active FirmMembership for that User and Firm;

Authentication first maps the exact Stytch Member/Organization pair through the bounded
`privexa_private.resolve_authenticated_identity` database function. That function is the only
pre-context identity lookup available to the runtime role; it is not a general unrestricted
session. Privexa then establishes transaction-local Firm scope.

For Client work, the application applies the validated membership and requested Client ID as a
transaction-local candidate scope. RLS checks that the ClientWorkspace belongs to the Firm and
applies the effective access rule:

- `FIRM_OWNER` and `FIRM_ADMIN`: allow an active ClientWorkspace in the same Firm;
- `CONSULTANT`, `REVIEWER`, and `READ_ONLY`: require an active ClientAccessGrant;
- inactive membership, wrong Firm, inactive ClientWorkspace, or unhandled role: deny.

Only a successful RLS-protected query produces the trusted `ClientContext`. The access-control
service binds that scope to exactly one typed Permission in a `FirmAuthorizationContext`,
`ClientAuthorizationContext`, or `SelfAuthorizationContext`. Context constructors require an
internal validation token so arbitrary IDs cannot be promoted through normal application code.
Knowing a Client UUID is never authorization.

The role policy is deterministic and default-deny. `FIRM_OWNER` receives every Build 0 permission.
`FIRM_ADMIN` receives the same permissions except Firm-owner lifecycle management. `CONSULTANT`,
`REVIEWER`, and `READ_ONLY` receive basic Firm visibility, self-profile access, and read access to
assigned clients. Future privacy modules add explicit domain permissions rather than inheriting a
generic client-resource write permission.

Client-scoped repositories require this context and query by both tenant identifiers.
`apply_firm_scope` and `apply_client_scope` set PostgreSQL configuration values with
transaction-local `set_config` calls. The settings are `privexa.user_id`,
`privexa.membership_id`, `privexa.firm_id`, and `privexa.client_id`. They disappear at commit or
rollback, so a pooled connection cannot carry one request's scope into another transaction.

One SQLAlchemy Session is permanently bound to one actor and Firm and may narrow to at most one
Client. Scope switching raises an internal security error. This matters because SQLAlchemy's
identity map can return a previously loaded object without executing another RLS-protected query.
Portfolio or background work over several Clients must open a new Session per Client.

RLS is enabled and forced on `firms`, `users`, `firm_memberships`, `client_workspaces`, and
`client_access_grants`. Policies fail closed without context and private policy helpers re-check
active identity and authorization relationships. Firm and Client Workspace updates are limited to
their validated scope; Client Workspace inserts require an Owner/Admin candidate scope; hard deletes
are denied. Membership and Client access-grant mutations remain denied because their management
services are not implemented. Future administration must add an explicitly authorized service and
command-specific RLS policy.

The FastAPI runtime role is a non-owner without superuser or `BYPASSRLS` authority. Startup validates
those attributes and verifies forced RLS on the protected-table inventory. Alembic uses the separate
schema-owner URL. Private `SECURITY DEFINER` functions use a fixed `pg_catalog` search path,
schema-qualified tables, revoked `PUBLIC` execution, and grants only to the configured runtime role.
Table grants mirror the implemented commands: Firm/User read-update, Membership/AccessGrant read,
and ClientWorkspace read-insert-update. The runtime role has no protected-table DELETE privilege.

Client creation is limited to an Owner/Admin whose validated Firm candidate context names the new
Client UUID. The SELECT policy admits that active candidate row so PostgreSQL `INSERT ... RETURNING`
works without granting broader Client visibility. Firm/user administration flows still need
explicit authorization policies in their owning PBIs.

## Application authorization

Protected HTTP routes use `require_firm_permission(...)`, `require_client_permission(...)`, or
`require_self_permission(...)`.
These dependencies authenticate first, produce action-bound authorization context, and translate
private authorization failures into stable API behavior:

- missing or invalid authentication is `401`;
- a prohibited action in a valid visible scope is `403`;
- an absent, inactive, unassigned, cross-Firm, or cross-client resource is `404`.

Application services require action-bound authorization context and verify their expected Permission
before calling repositories. Repositories receive `FirmContext` or `ClientContext` and scope queries
before returning records. Create operations derive security ownership from those contexts; normal
update DTOs must not expose ownership columns.

Authorization denials are logged with internal IDs, Permission, private reason code, and request ID.
Tokens, provider secrets, names, and client privacy content are never authorization-log fields.

## Lifecycle and deletion

Foundational records use explicit lifecycle state. Foreign keys use `ON DELETE RESTRICT`; routine
hard deletion and destructive cascades are not supported. Archival and revocation timestamps must
agree with their corresponding status.

All timestamps are timezone-aware PostgreSQL timestamps. Creation and update expressions use the
database clock and represent UTC instants.

## AI, agents, workers, and billing

AI and agents never infer Firm or Client identity. A future execution receives the initiating actor
and intended Firm/Client scope, then obtains the same action-bound authorization context used by a
human request. Background jobs must carry stable actor, Firm, and Client IDs and re-establish
authorization when execution begins. There is no AI or agent administrator bypass.

Firm is the future subscription and seat boundary. Usage generated for a client can carry both IDs,
allowing it to aggregate to the Firm while remaining attributable to the ClientWorkspace.
