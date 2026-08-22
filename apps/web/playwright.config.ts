import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  forbidOnly: true,
  use: {
    baseURL: "http://127.0.0.1:3100",
    trace: "retain-on-failure",
  },
  webServer: [
    {
      command: "node e2e/support/mock-api.mjs",
      url: "http://127.0.0.1:4010/health",
      reuseExistingServer: true,
    },
    {
      command:
        "PRIVEXA_UI_HARNESS_ENABLED=true PRIVEXA_E2E_AUTH_BYPASS=true PRIVEXA_NEXT_DIST_DIR=.next-e2e PRIVEXA_API_URL=http://127.0.0.1:4010 npm run dev -- --hostname 127.0.0.1 --port 3100",
      port: 3100,
      reuseExistingServer: false,
    },
  ],
});
