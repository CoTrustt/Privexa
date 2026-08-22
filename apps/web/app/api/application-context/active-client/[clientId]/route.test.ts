// @vitest-environment node

import { NextRequest } from "next/server";
import { afterEach, describe, expect, it, vi } from "vitest";

import { PUT } from "./route";

const clientId = "00000000-0000-4000-8000-000000000002";

afterEach(() => {
  vi.unstubAllGlobals();
});

function request(origin = "http://localhost:3000") {
  return new NextRequest(`http://localhost:3000/api/application-context/active-client/${clientId}`, {
    method: "PUT",
    headers: {
      origin,
      cookie: "stytch_session=opaque-token; unrelated_cookie=must-not-forward",
      "x-request-id": "request-123",
    },
  });
}

describe("PUT /api/application-context/active-client/[clientId]", () => {
  it("rejects cross-origin and malformed requests before contacting the API", async () => {
    const upstreamFetch = vi.fn();
    vi.stubGlobal("fetch", upstreamFetch);

    const crossOrigin = await PUT(request("https://attacker.example"), {
      params: Promise.resolve({ clientId }),
    });
    const malformed = await PUT(request(), {
      params: Promise.resolve({ clientId: "not-a-uuid" }),
    });

    expect(crossOrigin.status).toBe(403);
    expect(malformed.status).toBe(400);
    expect(upstreamFetch).not.toHaveBeenCalled();
  });

  it("forwards only the requested identifier, opaque session, origin, and request id", async () => {
    const upstreamFetch = vi.fn().mockResolvedValue(
      Response.json({ active_client: { id: clientId, display_name: "Apollo Finance" } }),
    );
    vi.stubGlobal("fetch", upstreamFetch);

    const response = await PUT(request(), { params: Promise.resolve({ clientId }) });

    expect(response.status).toBe(200);
    expect(upstreamFetch).toHaveBeenCalledWith(
      `http://localhost:8000/v1/application-context/active-client/${clientId}`,
      expect.objectContaining({
        method: "PUT",
        cache: "no-store",
        headers: {
          Cookie: "stytch_session=opaque-token",
          Origin: "http://localhost:3000",
          "X-Request-ID": "request-123",
        },
      }),
    );
    expect(response.headers.get("cache-control")).toBe("no-store");
  });

  it("does not expose infrastructure details when the API is unavailable", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("private network details")));

    const response = await PUT(request(), { params: Promise.resolve({ clientId }) });

    expect(response.status).toBe(503);
    await expect(response.json()).resolves.toEqual({
      code: "APPLICATION_CONTEXT_UNAVAILABLE",
      detail: "Your workspace could not be changed right now.",
    });
  });
});
