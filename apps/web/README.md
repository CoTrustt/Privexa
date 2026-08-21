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
