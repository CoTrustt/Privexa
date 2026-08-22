import { describe, expect, it } from "vitest";

import {
  clearRememberedReturnTo,
  readRememberedReturnTo,
  rememberReturnTo,
  safeReturnTo,
  signInPath,
} from "./return-to";

describe("safeReturnTo", () => {
  it.each([undefined, null, "", "https://evil.example", "//evil.example", "javascript:alert(1)"])(
    "falls back for unsafe destination %s",
    (candidate) => {
      expect(safeReturnTo(candidate)).toBe("/");
    },
  );

  it("preserves an internal path with query and fragment", () => {
    expect(safeReturnTo("/clients?view=active#next")).toBe("/clients?view=active#next");
  });

  it("round-trips only a safe internal destination through the callback cookie", () => {
    rememberReturnTo("/clients?view=active");
    expect(readRememberedReturnTo()).toBe("/clients?view=active");

    rememberReturnTo("https://evil.example/steal");
    expect(readRememberedReturnTo()).toBe("/");
    clearRememberedReturnTo();
  });
});

describe("signInPath", () => {
  it("clears callback parameters when returning to the default sign-in page", () => {
    expect(signInPath("/")).toBe("/sign-in");
  });

  it("preserves a safe internal destination", () => {
    expect(signInPath("/clients?view=active")).toBe(
      "/sign-in?returnTo=%2Fclients%3Fview%3Dactive",
    );
  });

  it("drops an unsafe destination", () => {
    expect(signInPath("https://evil.example/steal")).toBe("/sign-in");
  });
});
