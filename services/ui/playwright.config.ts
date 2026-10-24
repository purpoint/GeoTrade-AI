import { defineConfig, devices } from "@playwright/test";

// Runs against a live stack (`docker compose up` with seeded data): BASE_URL defaults to the UI port.
export default defineConfig({
  testDir: "tests/e2e",
  use: { baseURL: process.env.BASE_URL || "http://localhost:3000" },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"] } },
    { name: "phone", use: { ...devices["Pixel 7"] } },
  ],
});
