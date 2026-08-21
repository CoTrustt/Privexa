import { type NextRequest, NextResponse } from "next/server";

import type { AuthenticationProblem } from "@/lib/auth/types";

const apiUrl = process.env.PRIVEXA_API_URL ?? "http://localhost:8000";

export async function POST(request: NextRequest) {
  const configuredOrigin = (process.env.NEXT_PUBLIC_APP_URL ?? "http://localhost:3000").replace(
    /\/$/,
    "",
  );
  if (request.headers.get("origin") !== configuredOrigin) {
    return NextResponse.json(
      { code: "CSRF_ORIGIN_MISMATCH", detail: "The request origin was not accepted." },
      { status: 403, headers: { "Cache-Control": "no-store" } },
    );
  }

  try {
    const sessionToken = request.cookies.get("stytch_session")?.value;
    const upstream = await fetch(`${apiUrl}/v1/auth/logout`, {
      method: "POST",
      cache: "no-store",
      headers: {
        ...(sessionToken
          ? { Cookie: `stytch_session=${sessionToken}` }
          : {}),
        Origin: configuredOrigin,
      },
    });
    const response = new NextResponse(null, {
      status: upstream.status,
      headers: { "Cache-Control": "no-store" },
    });
    for (const cookie of upstream.headers.getSetCookie()) {
      response.headers.append("Set-Cookie", cookie);
    }
    return response;
  } catch {
    const problem: AuthenticationProblem = {
      code: "AUTHENTICATION_SERVICE_UNAVAILABLE",
      detail: "Sign-out could not be completed right now. Please try again.",
    };
    return NextResponse.json(problem, { status: 503, headers: { "Cache-Control": "no-store" } });
  }
}
