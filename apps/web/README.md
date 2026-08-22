# Privexa web

The web application uses Stytch B2B Discovery email magic links and a same-origin Next.js boundary
in front of the Privexa FastAPI authentication API.

Copy the web settings from the repository `.env.example` into `apps/web/.env.local`, then run
`npm install` and `npm run dev`. Run the API on `http://localhost:8000` first.

The callback URL configured in Stytch must include exactly `http://localhost:3000/authenticate` for test
projects and the equivalent HTTPS URL for deployed environments. Configure
`NEXT_PUBLIC_STYTCH_CUSTOM_BASE_URL` only after the Stytch custom domain is active. The custom
domain is what allows Stytch to issue HttpOnly cookies in production; localhost cookies are not
HttpOnly by platform limitation.

Privexa preserves an internal post-authentication destination in a ten-minute SameSite cookie. The
cookie contains only an already-validated relative path, never a session credential. This keeps the
Stytch callback URL fixed and prevents open redirects.

The authenticated workspace layout resolves `/v1/application-context` directly from the server
with `cache: "no-store"`. It renders firm, client, and account identity from that single safe
projection. Client changes go through the same-origin
`PUT /api/application-context/active-client/[clientId]` boundary, which forwards only the opaque
session cookie and requested stable Client ID. After an authorised switch, the browser performs a
hard server reload while a blocking transition covers stale workspace content.

The shell intentionally contains only the real Home route. It has explicit states for first client
selection, no authorised clients, unavailable membership, temporary context failure, and
client-side session expiry. Lists of eight or more clients gain search; a single active client is
rendered as non-interactive context.

The Ask Privexa work-note action reads a customer-safe capability projection once when it mounts.
It does not poll and the projection never grants execution authority. When AI is unavailable, only
the preparation action is disabled; the manual note remains editable and preserved. Backend
execution failures replace stale capability state with calm Privexa-language guidance and expose a
retry only when the normalized response is retryable. The work-note component can pass selected
stored-file IDs through the same-origin BFF; the BFF accepts only a bounded, unique UUID list and
forwards no caller-controlled model, provider, policy, or execution settings.

## Professional object UI foundation

Question, Processing Activity, Evidence, Obligation, Decision, and Action pages should map their
authorized API projection into `ProfessionalObjectPageViewModel` and render it through
`ProfessionalObjectShell`. The shell owns verified workspace orientation, object identity, status,
shared actions, the responsive inspector, and common loading/error/permission behavior. A domain
page supplies its own professional body as children; domain fields do not belong in the shell.

Lifecycle labels and semantic tones are presenter concerns because PBI 1.1 deliberately has no
universal status enum. Raw RFC 3339 timestamps and the positive concurrency version remain intact
in the view model. The shell requires the active Firm and Client Workspace IDs and fails closed if
they do not match the object's scope.

For local review, set `PRIVEXA_UI_HARNESS_ENABLED=true` and open
`/ui-harness/professional-objects/evidence` inside an authenticated development workspace. The harness
contains fictional typed fixtures for normal, long, empty, read-only, archived, loading, error,
section-recovery, optimistic rollback, and version-conflict states. It is not linked from product
navigation and returns 404 in production regardless of the flag.

Playwright starts a loopback-only application-context stub and sets
`PRIVEXA_E2E_AUTH_BYPASS=true` for its local development server. The flag bypasses browser-side
Stytch initialization and its expiry guard only in non-production builds; the server-side
opaque-cookie and application-context checks still run. Production ignores the bypass and omits
the UI harness.

## Question workflow

The active-client Overview shows the five most recent open Questions, with a dedicated filtered
list and a `ProfessionalObjectShell` detail page. Authorized members can create and edit
human-authored question text and context, then use the explicit resolve, close, and reopen
lifecycle commands. Forms use React Hook Form with Zod validation aligned to the API limits and
preserve drafts after failed mutations or optimistic-version conflicts.

Server Components read Question projections directly from FastAPI with `cache: "no-store"`.
Browser mutations use narrow same-origin Next.js handlers that validate Origin, UUID path values,
payload shape, and optimistic version before forwarding only the opaque session cookie. The
application-context Question capability projection controls whether mutation affordances are
shown; FastAPI authorization and PostgreSQL RLS remain authoritative for every operation.
