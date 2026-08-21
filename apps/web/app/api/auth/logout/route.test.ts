// @vitest-environment node

import { NextRequest } from "next/server";
import { afterEach, describe, expect, it, vi } from "vitest";

import { POST } from "./route";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("POST /api/auth/logout", () => {
  it("rejects a cross-origin request before contacting the API", async () => {
    const upstreamFetch = vi.fn();
    vi.stubGlobal("fetch", upstreamFetch);
    const request = new NextRequest("http://localhost:3000/api/auth/logout", {
      method: "POST",
      headers: { origin: "https://attacker.example", cookie: "stytch_session=opaque-token" },
    });

    const response = await POST(request);

    expect(response.status).toBe(403);
    expect(upstreamFetch).not.toHaveBeenCalled();
  });

  it("forwards the trusted origin and only the Stytch session cookie", async () => {
    const upstreamFetch = vi.fn().mockResolvedValue(
      new Response(null, {
        status: 204,
        headers: { "Set-Cookie": "stytch_session=; Path=/; HttpOnly; SameSite=Lax" },
      }),
    );
    vi.stubGlobal("fetch", upstreamFetch);
    const request = new NextRequest("http://localhost:3000/api/auth/logout", {
      method: "POST",
      headers: {
        origin: "http://localhost:3000",
        cookie: "stytch_session=opaque-token; unrelated_cookie=must-not-forward",
      },
    });

    const response = await POST(request);

    expect(response.status).toBe(204);
    expect(upstreamFetch).toHaveBeenCalledWith(
      "http://localhost:8000/v1/auth/logout",
      expect.objectContaining({
        method: "POST",
        headers: {
          Cookie: "stytch_session=opaque-token",
          Origin: "http://localhost:3000",
        },
      }),
    );
    expect(response.headers.get("set-cookie")).toContain("stytch_session=");
  });
});
