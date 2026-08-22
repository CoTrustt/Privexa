import { describe, expect, it } from "vitest";

import { formatProfessionalTimestamp } from "./date-time";

describe("formatProfessionalTimestamp", () => {
  it("preserves an absolute machine timestamp and uses one professional display convention", () => {
    const result = formatProfessionalTimestamp("2026-08-22T09:20:00.000Z");

    expect(result?.dateTime).toBe("2026-08-22T09:20:00.000Z");
    expect(result?.label).toContain("22 Aug 2026");
    expect(result?.label).toContain("IST");
  });

  it("fails safely for missing or invalid values", () => {
    expect(formatProfessionalTimestamp(undefined)).toBeNull();
    expect(formatProfessionalTimestamp("not-a-date")).toBeNull();
  });
});
