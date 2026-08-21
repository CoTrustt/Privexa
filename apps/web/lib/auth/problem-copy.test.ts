import { describe, expect, it } from "vitest";

import { copyForProblem } from "./problem-copy";

describe("copyForProblem", () => {
  it("keeps session expiry distinct from an invalid firm membership", () => {
    expect(copyForProblem("SESSION_EXPIRED")).toContain("session ended");
    expect(copyForProblem("MEMBERSHIP_INACTIVE")).toContain("membership is inactive");
  });

  it("does not reveal an unknown backend error", () => {
    expect(copyForProblem("provider_stack_trace_123")).toBe(
      "We could not complete sign-in. Please try again.",
    );
  });
});
