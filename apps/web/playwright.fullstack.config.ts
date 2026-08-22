import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  testMatch: "questions.fullstack.spec.ts",
  fullyParallel: false,
  forbidOnly: true,
  workers: 1,
  use: {
    baseURL: "http://127.0.0.1:3200",
    trace: "retain-on-failure",
  },
  webServer: [
    {
      command: "cd ../api && uv run python tests/e2e_server.py",
      url: "http://127.0.0.1:4020/health",
      reuseExistingServer: false,
      timeout: 120_000,
      env: {
        ...process.env,
        PRIVEXA_ENVIRONMENT: "test",
        PRIVEXA_WEB_ORIGIN: "http://127.0.0.1:3200",
        PRIVEXA_E2E_API_PORT: "4020",
        AI_GATEWAY_ENABLED: "false",
        AI_PROVIDER_MODE: "disabled",
      },
    },
    {
      command:
        "NEXT_PUBLIC_APP_URL=http://127.0.0.1:3200 PRIVEXA_E2E_AUTH_BYPASS=true PRIVEXA_NEXT_DIST_DIR=.next-fullstack PRIVEXA_API_URL=http://127.0.0.1:4020 npm run dev -- --hostname 127.0.0.1 --port 3200",
      port: 3200,
      reuseExistingServer: false,
      timeout: 120_000,
    },
  ],
});
