import { defineConfig } from "@playwright/test";

const baseURL = process.env.E2E_BASE_URL || "http://localhost:8000";

export default defineConfig({
  testDir: "./e2e",
  timeout: 90_000,
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL,
    // Uses the installed Edge, so no browser download is needed. Set E2E_CHANNEL=chrome to change it.
    channel: process.env.E2E_CHANNEL || "msedge",
    viewport: { width: 1440, height: 900 },
    trace: "retain-on-failure",
  },
});
