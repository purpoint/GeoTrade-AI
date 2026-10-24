import { defineConfig, devices } from "@playwright/test";

// Runs against a live stack (`docker compose up` with seeded data); BASE_URL defaults to the UI port.
// Serial: the operator journey resets demo data, which other journeys could otherwise observe.
export default defineConfig({
  testDir: "tests/e2e",
  workers: 1,
  fullyParallel: false,
  timeout: 60_000,
  expect: { timeout: 10_000 },
  use: { baseURL: process.env.BASE_URL || "http://localhost:3000", trace: "retain-on-failure" },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"] } },
    { name: "phone", use: { ...devices["Pixel 7"] } },
  ],
});
