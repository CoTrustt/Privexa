// @vitest-environment node

import { NextRequest } from "next/server";
import { afterEach, describe, expect, it, vi } from "vitest";

import { GET } from "./route";

afterEach(() => {
  vi.unstubAllGlobals();
});

function request() {
  return new NextRequest("http://localhost:3000/api/ai/capability", {
    headers: {
      cookie: "stytch_session=opaque-token; unrelated_cookie=must-not-forward",
      "x-request-id": "request-availability-123",
    },
  });
}

describe("GET /api/ai/capability", () => {
  it("forwards only the session and request correlation without caching", async () => {
    const upstreamFetch = vi.fn().mockResolvedValue(
      Response.json({
        task_id: "ai.prepare_work_note",
        state: "AVAILABLE",
        available: true,
        retryable: false,
        retry_after_seconds: null,
      }),
    );
    vi.stubGlobal("fetch", upstreamFetch);

    const response = await GET(request());

    expect(upstreamFetch).toHaveBeenCalledWith(
      "http://localhost:8000/v1/ai/tasks/ai.prepare_work_note/capability",
      {
        method: "GET",
        cache: "no-store",
        headers: {
          Cookie: "stytch_session=opaque-token",
          "X-Request-ID": "request-availability-123",
        },
      },
    );
    expect(response.headers.get("cache-control")).toBe("no-store");
  });

  it("normalizes an API outage without exposing diagnostics", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockRejectedValue(
          new Error("private provider and upstream diagnostics"),
        ),
    );

    const response = await GET(request());
    const body = await response.json();

    expect(response.status).toBe(503);
    expect(body).toEqual({
      task_id: "ai.prepare_work_note",
      state: "TEMPORARILY_UNAVAILABLE",
      available: false,
      retryable: true,
      retry_after_seconds: null,
    });
    expect(JSON.stringify(body)).not.toContain("provider");
    expect(JSON.stringify(body)).not.toContain("diagnostics");
  });
});
