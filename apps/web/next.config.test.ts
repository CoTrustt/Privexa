// @vitest-environment node

import { describe, expect, it } from "vitest";

import nextConfig from "./next.config";

describe("Next.js request logging", () => {
  it("suppresses the authentication callback because its query contains a one-time token", () => {
    const logging = nextConfig.logging;
    if (!logging) {
      throw new Error("Incoming request logging must be configured");
    }

    const incomingRequests = logging.incomingRequests;
    if (!incomingRequests || incomingRequests === true) {
      throw new Error("Incoming request ignore rules must be configured");
    }

    const ignored = incomingRequests.ignore ?? [];
    expect(ignored.some((pattern) => pattern.test("/authenticate?token=one-time-secret"))).toBe(
      true,
    );
    expect(ignored.some((pattern) => pattern.test("/sign-in"))).toBe(false);
  });
});
