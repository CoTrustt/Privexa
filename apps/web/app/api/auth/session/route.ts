import { type NextRequest, NextResponse } from "next/server";

import type { AuthenticationProblem } from "@/lib/auth/types";

const apiUrl = process.env.PRIVEXA_API_URL ?? "http://localhost:8000";

export const dynamic = "force-dynamic";

export async function GET(request: NextRequest) {
  const sessionToken = request.cookies.get("stytch_session")?.value;
  const requestId = request.headers.get("x-request-id");

  try {
    const upstream = await fetch(`${apiUrl}/v1/auth/session`, {
      cache: "no-store",
      headers: {
        ...(sessionToken
          ? { Cookie: `stytch_session=${sessionToken}` }
          : {}),
        ...(requestId ? { "X-Request-ID": requestId } : {}),
      },
    });
    const body = await upstream.text();

    return new NextResponse(body, {
      status: upstream.status,
      headers: {
        "Cache-Control": "private, no-store",
        "Content-Type": upstream.headers.get("content-type") ?? "application/json",
      },
    });
  } catch {
    const problem: AuthenticationProblem = {
      code: "AUTHENTICATION_SERVICE_UNAVAILABLE",
      detail: "Sign-in could not be verified right now. Please try again.",
    };
    return NextResponse.json(problem, { status: 503, headers: { "Cache-Control": "no-store" } });
  }
}
