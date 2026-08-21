// @vitest-environment node

import { NextRequest } from "next/server";
import { describe, expect, it } from "vitest";

import { proxy } from "./proxy";

describe("workspace proxy", () => {
  it("preserves a safe internal destination for an unauthenticated request", () => {
    const response = proxy(new NextRequest("http://localhost:3000/?view=briefing"));
    const location = new URL(response.headers.get("location")!);

    expect(response.status).toBe(307);
    expect(location.pathname).toBe("/sign-in");
    expect(location.searchParams.get("reason")).toBe("AUTHENTICATION_REQUIRED");
    expect(location.searchParams.get("returnTo")).toBe("/?view=briefing");
  });

  it("allows the request to reach the authoritative server check when a cookie exists", () => {
    const request = new NextRequest("http://localhost:3000/", {
      headers: { cookie: "stytch_session=opaque-token" },
    });

    const response = proxy(request);

    expect(response.headers.get("x-middleware-next")).toBe("1");
  });
});
