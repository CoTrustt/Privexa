import { AuthFlowType, B2BProducts } from "@stytch/nextjs/b2b";
import { describe, expect, it } from "vitest";

import { buildStytchConfig } from "./stytch-config";

describe("buildStytchConfig", () => {
  it("uses the Stytch B2B discovery magic-link flow without self-service firms", () => {
    const config = buildStytchConfig({
      appUrl: "https://app.privexa.example/",
      destination: "/clients?view=active",
      sessionDurationMinutes: 240,
    });

    expect(config.authFlowType).toBe(AuthFlowType.Discovery);
    expect(config.products).toEqual([B2BProducts.emailMagicLinks]);
    expect(config.emailMagicLinksOptions?.discoveryRedirectURL).toBe(
      "https://app.privexa.example/authenticate",
    );
    expect(config.directLoginForSingleMembership).toEqual({
      status: true,
      ignoreInvites: false,
      ignoreJitProvisioning: false,
    });
    expect(config.directCreateOrganizationForNoMembership).toBe(false);
    expect(config.disableCreateOrganization).toBe(true);
  });

  it("falls back to an eight-hour session when configuration is invalid", () => {
    const config = buildStytchConfig({
      appUrl: "http://localhost:3000",
      destination: "/",
      sessionDurationMinutes: Number.NaN,
    });

    expect(config.sessionOptions.sessionDurationMinutes).toBe(480);
  });
});
