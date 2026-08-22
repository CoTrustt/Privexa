import { type NextRequest, NextResponse } from "next/server";

const apiUrl = process.env.PRIVEXA_API_URL ?? "http://localhost:8000";

export async function GET(request: NextRequest) {
  const sessionToken = request.cookies.get("stytch_session")?.value;
  const requestId = request.headers.get("x-request-id");
  try {
    const upstream = await fetch(
      `${apiUrl}/v1/ai/tasks/ai.prepare_work_note/capability`,
      {
        method: "GET",
        cache: "no-store",
        headers: {
          ...(sessionToken ? { Cookie: `stytch_session=${sessionToken}` } : {}),
          ...(requestId ? { "X-Request-ID": requestId } : {}),
        },
      },
    );
    return new NextResponse(await upstream.text(), {
      status: upstream.status,
      headers: {
        "Cache-Control": "no-store",
        "Content-Type":
          upstream.headers.get("content-type") ?? "application/json",
      },
    });
  } catch {
    return NextResponse.json(
      {
        task_id: "ai.prepare_work_note",
        state: "TEMPORARILY_UNAVAILABLE",
        available: false,
        retryable: true,
        retry_after_seconds: null,
      },
      { status: 503, headers: { "Cache-Control": "no-store" } },
    );
  }
}
