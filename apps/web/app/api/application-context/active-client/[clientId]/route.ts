import { type NextRequest, NextResponse } from "next/server";

import type { ApplicationContextProblem } from "@/lib/application-context/types";

const apiUrl = process.env.PRIVEXA_API_URL ?? "http://localhost:8000";
const uuidPattern = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

export async function PUT(
  request: NextRequest,
  { params }: { params: Promise<{ clientId: string }> },
) {
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

  const { clientId } = await params;
  if (!uuidPattern.test(clientId)) {
    return NextResponse.json(
      { code: "INVALID_CLIENT_IDENTIFIER", detail: "The requested workspace is unavailable." },
      { status: 400, headers: { "Cache-Control": "no-store" } },
    );
  }

  try {
    const sessionToken = request.cookies.get("stytch_session")?.value;
    const requestId = request.headers.get("x-request-id");
    const upstream = await fetch(
      `${apiUrl}/v1/application-context/active-client/${encodeURIComponent(clientId)}`,
      {
        method: "PUT",
        cache: "no-store",
        headers: {
          ...(sessionToken ? { Cookie: `stytch_session=${sessionToken}` } : {}),
          ...(requestId ? { "X-Request-ID": requestId } : {}),
          Origin: configuredOrigin,
        },
      },
    );
    const body = await upstream.text();
    return new NextResponse(body, {
      status: upstream.status,
      headers: {
        "Cache-Control": "no-store",
        "Content-Type": upstream.headers.get("content-type") ?? "application/json",
      },
    });
  } catch {
    const problem: ApplicationContextProblem = {
      code: "APPLICATION_CONTEXT_UNAVAILABLE",
      detail: "Your workspace could not be changed right now.",
    };
    return NextResponse.json(problem, {
      status: 503,
      headers: { "Cache-Control": "no-store" },
    });
  }
}
