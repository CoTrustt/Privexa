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
