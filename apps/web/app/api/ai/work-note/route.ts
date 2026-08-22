import { type NextRequest, NextResponse } from "next/server";

const apiUrl = process.env.PRIVEXA_API_URL ?? "http://localhost:8000";
const uuidPattern =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

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

  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json(
      { code: "AI_INVALID_INPUT", detail: "Enter a work note before preparing a draft." },
      { status: 400, headers: { "Cache-Control": "no-store" } },
    );
  }
  const note =
    typeof body === "object" && body !== null ? (body as Record<string, unknown>).note : null;
  const sourceFileIds =
    typeof body === "object" && body !== null
      ? (body as Record<string, unknown>).source_file_ids
      : undefined;
  if (typeof note !== "string" || note.trim().length < 1 || note.length > 5_000) {
    return NextResponse.json(
      { code: "AI_INVALID_INPUT", detail: "Enter a work note of 5,000 characters or fewer." },
      { status: 400, headers: { "Cache-Control": "no-store" } },
    );
  }
  if (
    sourceFileIds !== undefined &&
    (!Array.isArray(sourceFileIds) ||
      sourceFileIds.length > 100 ||
      sourceFileIds.some((value) => typeof value !== "string" || !uuidPattern.test(value)) ||
      new Set((sourceFileIds as string[]).map((value) => value.toLowerCase())).size !==
        sourceFileIds.length)
  ) {
    return NextResponse.json(
      {
        code: "AI_INVALID_INPUT",
        detail: "Select no more than 100 unique stored files.",
      },
      { status: 400, headers: { "Cache-Control": "no-store" } },
    );
  }

  try {
    const sessionToken = request.cookies.get("stytch_session")?.value;
    const requestId = request.headers.get("x-request-id");
    const upstream = await fetch(`${apiUrl}/v1/ai/tasks/ai.prepare_work_note/prepare`, {
      method: "POST",
      cache: "no-store",
      headers: {
        "Content-Type": "application/json",
        ...(sessionToken ? { Cookie: `stytch_session=${sessionToken}` } : {}),
        ...(requestId ? { "X-Request-ID": requestId } : {}),
        Origin: configuredOrigin,
      },
      body: JSON.stringify({ note, source_file_ids: sourceFileIds ?? [] }),
    });
    return new NextResponse(await upstream.text(), {
      status: upstream.status,
      headers: {
        "Cache-Control": "no-store",
        "Content-Type": upstream.headers.get("content-type") ?? "application/json",
      },
    });
  } catch {
    return NextResponse.json(
      {
        status: "FAILED",
        execution_id: "00000000-0000-0000-0000-000000000000",
        candidate: null,
        problem: {
          code: "AI_PROVIDER_UNAVAILABLE",
          detail: "Preparation is temporarily unavailable. Your manual note is unchanged.",
          retryable: true,
          retry_after_seconds: null,
        },
      },
      { status: 503, headers: { "Cache-Control": "no-store" } },
    );
  }
}
