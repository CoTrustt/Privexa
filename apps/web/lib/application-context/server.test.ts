// @vitest-environment node

import { afterEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  sessionToken: undefined as string | undefined,
}));

vi.mock("server-only", () => ({}));
vi.mock("next/headers", () => ({
  cookies: async () => ({
    get: (name: string) =>
      name === "stytch_session" && mocks.sessionToken
        ? { name, value: mocks.sessionToken }
        : undefined,
  }),
}));

import { getServerApplicationContext } from "./server";

const responseBody = {
  state: "ACTIVE_CLIENT",
  user: { id: "user-1", display_name: "Consultant Alice" },
  firm: { id: "firm-1", display_name: "Pai Privacy Consulting" },
  active_client: { id: "client-1", display_name: "Apollo Finance" },
  authorised_clients: [{ id: "client-1", display_name: "Apollo Finance" }],
};

afterEach(() => {
  mocks.sessionToken = undefined;
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

describe("getServerApplicationContext", () => {
  it("fails closed without forwarding a request when the server session cookie is absent", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    await expect(getServerApplicationContext()).resolves.toEqual({
      ok: false,
      status: 401,
      problem: { code: "AUTHENTICATION_REQUIRED", detail: "Sign in to continue." },
    });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("fetches each authenticated context with its own opaque cookie and no shared cache", async () => {
    const fetchMock = vi.fn().mockImplementation(async (_url, options: RequestInit) => {
      const cookie = (options.headers as Record<string, string>).Cookie;
      const clientName = cookie.includes("session-b") ? "Northstar Health" : "Apollo Finance";
      return Response.json({
        ...responseBody,
        active_client: { id: `${clientName}-id`, display_name: clientName },
        authorised_clients: [{ id: `${clientName}-id`, display_name: clientName }],
      });
    });
    vi.stubGlobal("fetch", fetchMock);

    mocks.sessionToken = "session-a";
    const userA = await getServerApplicationContext();
    mocks.sessionToken = "session-b";
    const userB = await getServerApplicationContext();

    expect(userA.ok && userA.context.active_client?.display_name).toBe("Apollo Finance");
    expect(userB.ok && userB.context.active_client?.display_name).toBe("Northstar Health");
    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "http://localhost:8000/v1/application-context",
      { cache: "no-store", headers: { Cookie: "stytch_session=session-a" } },
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "http://localhost:8000/v1/application-context",
      { cache: "no-store", headers: { Cookie: "stytch_session=session-b" } },
    );
  });

  it("maps malformed or failed upstream responses to a safe temporary problem", async () => {
    mocks.sessionToken = "session-a";
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json({ stack: "private trace" })));

    await expect(getServerApplicationContext()).resolves.toEqual({
      ok: false,
      status: 503,
      problem: {
        code: "APPLICATION_CONTEXT_UNAVAILABLE",
        detail: "Your workspace could not be established right now.",
      },
    });

    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("private network address")));
    await expect(getServerApplicationContext()).resolves.toEqual({
      ok: false,
      status: 503,
      problem: {
        code: "APPLICATION_CONTEXT_UNAVAILABLE",
        detail: "Your workspace could not be established right now.",
      },
    });
  });
});
