// @vitest-environment node

import { NextRequest } from "next/server";
import { afterEach, describe, expect, it, vi } from "vitest";

import { POST } from "./route";

afterEach(() => {
  vi.unstubAllGlobals();
});

function request(body: unknown, origin = "http://localhost:3000") {
  return new NextRequest("http://localhost:3000/api/ai/work-note", {
    method: "POST",
    headers: {
      origin,
      cookie: "stytch_session=opaque-token; unrelated_cookie=must-not-forward",
      "content-type": "application/json",
      "x-request-id": "request-123",
    },
    body: JSON.stringify(body),
  });
}

describe("POST /api/ai/work-note", () => {
  it("rejects cross-origin and over-limit input before contacting the API", async () => {
    const upstreamFetch = vi.fn();
    vi.stubGlobal("fetch", upstreamFetch);

    const crossOrigin = await POST(request({ note: "Synthetic note" }, "https://attacker.example"));
    const overLimit = await POST(request({ note: "x".repeat(5_001) }));
    const duplicateSources = await POST(
      request({
        note: "Synthetic note",
        source_file_ids: [
          "abcdefab-cdef-4abc-8def-abcdefabcdef",
          "ABCDEFAB-CDEF-4ABC-8DEF-ABCDEFABCDEF",
        ],
      }),
    );

    expect(crossOrigin.status).toBe(403);
    expect(overLimit.status).toBe(400);
    expect(duplicateSources.status).toBe(400);
    expect(upstreamFetch).not.toHaveBeenCalled();
  });

  it("forwards only bounded task input, the opaque session, origin, and request ID", async () => {
    const upstreamFetch = vi.fn().mockResolvedValue(
      Response.json({
        status: "PREPARED",
        execution_id: "00000000-0000-4000-8000-000000000201",
        candidate: null,
        problem: null,
      }),
    );
    vi.stubGlobal("fetch", upstreamFetch);

    const response = await POST(
      request({
        note: "x".repeat(5_000),
        source_file_ids: ["00000000-0000-4000-8000-000000000301"],
        model: "attacker/chosen-model",
        retries: 100,
        timeout: 99_999,
        policy_outcome: "ALLOW",
      }),
    );

    expect(response.status).toBe(200);
    expect(upstreamFetch).toHaveBeenCalledWith(
      "http://localhost:8000/v1/ai/tasks/ai.prepare_work_note/prepare",
      expect.objectContaining({
        method: "POST",
        cache: "no-store",
        headers: {
          "Content-Type": "application/json",
          Cookie: "stytch_session=opaque-token",
          Origin: "http://localhost:3000",
          "X-Request-ID": "request-123",
        },
        body: JSON.stringify({
          note: "x".repeat(5_000),
          source_file_ids: ["00000000-0000-4000-8000-000000000301"],
        }),
      }),
    );
    expect(response.headers.get("cache-control")).toBe("no-store");
  });

  it("returns a stable local failure without leaking upstream diagnostics", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new Error("private upstream URL and provider diagnostics")),
    );

    const response = await POST(request({ note: "Synthetic note" }));

    expect(response.status).toBe(503);
    const body = await response.json();
    expect(body.problem).toEqual({
      code: "AI_PROVIDER_UNAVAILABLE",
      detail: "Preparation is temporarily unavailable. Your manual note is unchanged.",
      retryable: true,
      retry_after_seconds: null,
    });
    expect(JSON.stringify(body)).not.toContain("private upstream URL");
    expect(JSON.stringify(body)).not.toContain("provider diagnostics");
  });
});
