import "server-only";

import { type NextRequest, NextResponse } from "next/server";
import type { z } from "zod";

import { isQuestionIdentifier } from "./contracts";

const apiUrl = process.env.PRIVEXA_API_URL ?? "http://localhost:8000";

function noStoreJson(body: object, status: number) {
  return NextResponse.json(body, { status, headers: { "Cache-Control": "no-store" } });
}

export function validateQuestionOrigin(request: NextRequest): NextResponse | null {
  const configuredOrigin = (process.env.NEXT_PUBLIC_APP_URL ?? "http://localhost:3000").replace(
    /\/$/,
    "",
  );
  if (request.headers.get("origin") === configuredOrigin) return null;
  return noStoreJson(
    { code: "CSRF_ORIGIN_MISMATCH", detail: "The request origin was not accepted." },
    403,
  );
}

export function validateQuestionIdentifiers(...identifiers: string[]): NextResponse | null {
  if (identifiers.every(isQuestionIdentifier)) return null;
  return noStoreJson(
    { code: "INVALID_IDENTIFIER", detail: "The requested question is unavailable." },
    400,
  );
}

export async function parseQuestionMutation<T>(
  request: NextRequest,
  schema: z.ZodType<T>,
): Promise<{ ok: true; data: T } | { ok: false; response: NextResponse }> {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return {
      ok: false,
      response: noStoreJson(
        { code: "INVALID_REQUEST", detail: "The request body is not valid JSON." },
        400,
      ),
    };
  }
  const parsed = schema.safeParse(body);
  if (!parsed.success) {
    return {
      ok: false,
      response: noStoreJson(
        { code: "QUESTION_VALIDATION_FAILED", detail: parsed.error.issues[0]?.message ?? "Review the question and try again." },
        422,
      ),
    };
  }
  return { ok: true, data: parsed.data };
}

export async function forwardQuestionMutation({
  request,
  path,
  method,
  body,
  operation,
}: {
  request: NextRequest;
  path: string;
  method: "POST" | "PATCH";
  body: object;
  operation: "create" | "update" | "resolve" | "close" | "reopen";
}): Promise<NextResponse> {
  const configuredOrigin = (process.env.NEXT_PUBLIC_APP_URL ?? "http://localhost:3000").replace(
    /\/$/,
    "",
  );
  const sessionToken = request.cookies.get("stytch_session")?.value;
  const requestId = request.headers.get("x-request-id");
  try {
    const upstream = await fetch(`${apiUrl}${path}`, {
      method,
      cache: "no-store",
      headers: {
        "Content-Type": "application/json",
        ...(sessionToken ? { Cookie: `stytch_session=${sessionToken}` } : {}),
        ...(requestId ? { "X-Request-ID": requestId } : {}),
        Origin: configuredOrigin,
      },
      body: JSON.stringify(body),
    });
    return new NextResponse(await upstream.text(), {
      status: upstream.status,
      headers: {
        "Cache-Control": "no-store",
        "Content-Type": upstream.headers.get("content-type") ?? "application/json",
        ...(upstream.headers.get("location")
          ? { Location: upstream.headers.get("location") as string }
          : {}),
      },
    });
  } catch {
    console.error("Question mutation upstream unavailable", { operation });
    return noStoreJson(
      {
        code: "QUESTION_SERVICE_UNAVAILABLE",
        detail: "The question could not be saved right now. Your work is unchanged.",
      },
      503,
    );
  }
}
