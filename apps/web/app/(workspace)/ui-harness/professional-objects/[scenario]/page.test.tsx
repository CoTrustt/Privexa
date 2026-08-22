import { afterEach, describe, expect, it, vi } from "vitest";

import ProfessionalObjectHarnessPage from "./page";

vi.mock("@/lib/application-context/server", () => ({
  getServerApplicationContext: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  notFound: () => {
    throw Object.assign(new Error("Not found"), {
      digest: "NEXT_HTTP_ERROR_FALLBACK;404",
    });
  },
}));

const evidenceParams = Promise.resolve({ scenario: "evidence" });

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("ProfessionalObjectHarnessPage", () => {
  it("returns not found when the development harness flag is disabled", async () => {
    vi.stubEnv("PRIVEXA_UI_HARNESS_ENABLED", "false");

    await expect(
      ProfessionalObjectHarnessPage({ params: evidenceParams }),
    ).rejects.toMatchObject({ digest: "NEXT_HTTP_ERROR_FALLBACK;404" });
  });

  it("returns not found in production even when the development flag is set", async () => {
    vi.stubEnv("NODE_ENV", "production");
    vi.stubEnv("PRIVEXA_UI_HARNESS_ENABLED", "true");

    await expect(
      ProfessionalObjectHarnessPage({ params: evidenceParams }),
    ).rejects.toMatchObject({ digest: "NEXT_HTTP_ERROR_FALLBACK;404" });
  });
});
