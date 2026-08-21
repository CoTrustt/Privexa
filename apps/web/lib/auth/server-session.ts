import "server-only";

import { cookies } from "next/headers";

import type { AuthenticationProblem, PrivexaSession, SessionResult } from "./types";

const apiUrl = process.env.PRIVEXA_API_URL ?? "http://localhost:8000";

const fallbackProblem: AuthenticationProblem = {
  code: "AUTHENTICATION_SERVICE_UNAVAILABLE",
  detail: "Sign-in could not be verified right now. Please try again.",
};

export async function getServerSession(): Promise<SessionResult> {
  const cookieStore = await cookies();
  const sessionToken = cookieStore.get("stytch_session")?.value;
  if (!sessionToken) {
    return {
      ok: false,
      status: 401,
      problem: {
        code: "AUTHENTICATION_REQUIRED",
        detail: "Sign in to continue.",
      },
    };
  }

  try {
    const response = await fetch(`${apiUrl}/v1/auth/session`, {
      cache: "no-store",
      headers: {
        Cookie: `stytch_session=${sessionToken}`,
      },
    });

    if (response.ok) {
      return { ok: true, session: (await response.json()) as PrivexaSession };
    }

    return {
      ok: false,
      status: response.status,
      problem: (await response.json()) as AuthenticationProblem,
    };
  } catch {
    return { ok: false, status: 503, problem: fallbackProblem };
  }
}
