import { describe, expect, it } from "vitest";

import { isApplicationContext } from "./types";

describe("isApplicationContext", () => {
  it("accepts the narrow application-facing context projection", () => {
    expect(
      isApplicationContext({
        state: "ACTIVE_CLIENT",
        user: { id: "user-1", display_name: "Asha Rao" },
        firm: { id: "firm-1", display_name: "Rao Privacy" },
        active_client: { id: "client-1", display_name: "Apollo Finance" },
        authorised_clients: [{ id: "client-1", display_name: "Apollo Finance" }],
      }),
    ).toBe(true);
  });

  it("rejects security internals and malformed nullable states", () => {
    expect(
      isApplicationContext({
        state: "ACTIVE_CLIENT",
        user: { id: "user-1", display_name: "Asha Rao" },
        firm: { id: "firm-1", display_name: "Rao Privacy" },
        active_client: undefined,
        authorised_clients: [],
      }),
    ).toBe(false);
  });
});
