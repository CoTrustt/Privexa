// @vitest-environment node

import { NextRequest } from "next/server";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("server-only", () => ({}));

import { POST } from "./route";

const clientId = "20000000-0000-4000-8000-000000000001";

function request(body: unknown, origin = "http://localhost:3000") {
  return new NextRequest(`http://localhost:3000/api/clients/${clientId}/questions`, {
    method: "POST",
    headers: {
      origin,
      "content-type": "application/json",
      cookie: "stytch_session=opaque-session; unrelated=private",
      "x-request-id": "request-123",
    },
    body: JSON.stringify(body),
  });
}

afterEach(() => vi.unstubAllGlobals());

describe("POST Question BFF", () => {
  it("rejects cross-origin, malformed identifiers, and whitespace-only input before upstream", async () => {
    const upstream = vi.fn();
    vi.stubGlobal("fetch", upstream);
    expect((await POST(request({ question_text: "Q", context: "" }, "https://attacker.example"), { params: Promise.resolve({ clientId }) })).status).toBe(403);
    expect((await POST(request({ question_text: "Q", context: "" }), { params: Promise.resolve({ clientId: "bad" }) })).status).toBe(400);
    expect((await POST(request({ question_text: "   ", context: "" }), { params: Promise.resolve({ clientId }) })).status).toBe(422);
    expect(upstream).not.toHaveBeenCalled();
  });

  it("derives the required domain title and forwards only the opaque session and validated payload", async () => {
    const upstream = vi.fn().mockResolvedValue(Response.json({ id: "question-id" }, { status: 201 }));
    vi.stubGlobal("fetch", upstream);
    const response = await POST(
      request({ question_text: "  May we retain this data?  ", context: "  " }),
      { params: Promise.resolve({ clientId }) },
    );
    expect(response.status).toBe(201);
    const [, options] = upstream.mock.calls[0] as [string, RequestInit];
    expect(options.headers).toEqual({
      "Content-Type": "application/json",
      Cookie: "stytch_session=opaque-session",
      Origin: "http://localhost:3000",
      "X-Request-ID": "request-123",
    });
    expect(JSON.parse(options.body as string)).toEqual({
      title: "May we retain this data?",
      question_text: "  May we retain this data?  ",
      context: null,
    });
  });
});
