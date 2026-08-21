// @vitest-environment node

import { NextRequest } from "next/server";
import { afterEach, describe, expect, it, vi } from "vitest";

import { GET } from "./route";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("GET /api/auth/session", () => {
  it("forwards only the opaque Stytch session cookie", async () => {
    const upstreamFetch = vi.fn().mockResolvedValue(
      Response.json({
        user_id: "user-1",
        membership_id: "membership-1",
        firm_id: "firm-1",
        role: "CONSULTANT",
        display_name: "Asha Rao",
        firm_name: "Rao Privacy",
      }),
    );
    vi.stubGlobal("fetch", upstreamFetch);
    const request = new NextRequest("http://localhost:3000/api/auth/session", {
      headers: {
        cookie: "stytch_session=opaque-token; unrelated_cookie=must-not-forward",
        "x-request-id": "request-123",
      },
    });

    const response = await GET(request);

    expect(response.status).toBe(200);
    expect(upstreamFetch).toHaveBeenCalledWith(
      "http://localhost:8000/v1/auth/session",
      expect.objectContaining({
        headers: {
          Cookie: "stytch_session=opaque-token",
          "X-Request-ID": "request-123",
        },
      }),
    );
    expect(response.headers.get("cache-control")).toBe("private, no-store");
  });

  it("returns a stable unavailable problem when the API cannot be reached", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("raw network details")));
    const request = new NextRequest("http://localhost:3000/api/auth/session");

    const response = await GET(request);

    expect(response.status).toBe(503);
    await expect(response.json()).resolves.toEqual({
      code: "AUTHENTICATION_SERVICE_UNAVAILABLE",
      detail: "Sign-in could not be verified right now. Please try again.",
    });
  });
});
