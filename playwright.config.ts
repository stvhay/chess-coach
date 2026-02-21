import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "tests/e2e",
  timeout: 30_000,
  retries: 0,
  use: {
    baseURL: "http://localhost:8000",
    headless: true,
  },
  projects: [
    {
      name: "chromium",
      use: { browserName: "chromium" },
    },
  ],
  webServer: {
    command: "uv run uvicorn server.main:app --app-dir src --port 8000",
    port: 8000,
    reuseExistingServer: !process.env.CI,
    timeout: 15_000,
  },
});
