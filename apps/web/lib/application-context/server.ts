import "server-only";

import { cookies } from "next/headers";

import {
  isApplicationContext,
  isApplicationContextProblem,
  type ApplicationContextProblem,
  type ApplicationContextResult,
} from "./types";

const apiUrl = process.env.PRIVEXA_API_URL ?? "http://localhost:8000";

const unavailableProblem: ApplicationContextProblem = {
  code: "APPLICATION_CONTEXT_UNAVAILABLE",
  detail: "Your workspace could not be established right now.",
};

export async function getServerApplicationContext(): Promise<ApplicationContextResult> {
  const cookieStore = await cookies();
  const sessionToken = cookieStore.get("stytch_session")?.value;
  if (!sessionToken) {
    return {
      ok: false,
      status: 401,
      problem: { code: "AUTHENTICATION_REQUIRED", detail: "Sign in to continue." },
    };
  }

  try {
    const response = await fetch(`${apiUrl}/v1/application-context`, {
      cache: "no-store",
      headers: { Cookie: `stytch_session=${sessionToken}` },
    });
    const body: unknown = await response.json();
    if (response.ok && isApplicationContext(body)) {
      return { ok: true, context: body };
    }
    if (!response.ok && isApplicationContextProblem(body)) {
      return { ok: false, status: response.status, problem: body };
    }
    return { ok: false, status: 503, problem: unavailableProblem };
  } catch {
    return { ok: false, status: 503, problem: unavailableProblem };
  }
}
