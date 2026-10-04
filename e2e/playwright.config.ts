import { defineConfig } from "@playwright/test";

// Runs against a live stack (docker compose up + seed). Override with E2E_BASE_URL.
export default defineConfig({
  testDir: "tests",
  timeout: 45_000,
  fullyParallel: false,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["github"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:8080",
    locale: "tr-TR",
    timezoneId: "Europe/Istanbul",
    viewport: { width: 1440, height: 900 },
    trace: "retain-on-failure",
  },
});
