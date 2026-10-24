import path from "node:path";
import { expect, request as pwRequest, test } from "@playwright/test";
import { loadSample, operator, signUp } from "./helpers";

const FIXTURES = path.resolve(__dirname, "../../../../data/fixtures/portfolio");

test("1: sign up, upload a Zerodha CSV, confirm, land on a populated dashboard", async ({ page }) => {
  await signUp(page);
  await page.locator('input[type="file"]').setInputFiles(path.join(FIXTURES, "zerodha_kite.csv"));
  await expect(page.getByText("4 matched to NIFTY 50")).toBeVisible();
  await page.getByRole("button", { name: /Import 5 holdings/ }).click();
  await page.getByRole("button", { name: "Go to my portfolio" }).click();
  await expect(page.getByText("5 (1 outside NIFTY 50)")).toBeVisible();
  await expect(page.getByRole("link", { name: "INFY" }).first()).toBeVisible();
  await expect(page.getByText("Portfolio news sentiment")).toBeVisible();
});

test("2: demo account sees a ranked Needs Attention feed with reasons", async ({ page }) => {
  await page.goto("/login");
  await page.getByRole("button", { name: "Try the demo account" }).click();
  await expect(page).toHaveURL(/\/portfolio/);
  await page.goto("/attention");
  await expect(page.getByRole("heading", { name: "Needs attention" })).toBeVisible();
  const groups = page.locator("section.card button[aria-expanded]");
  await expect(groups.first()).toBeVisible();
  expect(await groups.count()).toBeGreaterThanOrEqual(10);
  await page.getByRole("button", { name: "Weights…" }).click();
  await expect(page.getByRole("dialog", { name: "Attention weights" })).toBeVisible();
  await page.getByRole("button", { name: "Cancel" }).click();
});

test("3: a negative regulatory headline on a held stock alerts the holder live", async ({ page, baseURL }) => {
  const ops = await pwRequest.newContext({ baseURL });
  const session = await operator(ops);
  test.skip(session === null, "set E2E_OPERATOR_EMAIL and E2E_OPERATOR_PASSWORD to run the operator journey");
  await signUp(page);
  await loadSample(page); // holds ADANIENT
  await page.goto("/attention");
  await expect(page.getByRole("heading", { name: "Needs attention" })).toBeVisible();
  await expect(page.getByText("Live")).toBeVisible();
  const headers = { "X-CSRF-Token": session!.csrf };
  await ops.post("/api/v1/admin/demo/reset", { headers });
  const injected = await ops.post("/api/v1/admin/demo/inject", {
    headers,
    data: { title: `SEBI orders forensic audit of Adani Enterprises accounts, probe ${Date.now()}` },
  });
  expect(injected.status()).toBe(201);
  await expect(page.getByRole("alert").filter({ hasText: "ADANIENT" })).toBeVisible({ timeout: 15_000 });
  await expect(page.getByTestId("bell-count")).toHaveText(/[1-9]/);
  await ops.post("/api/v1/admin/demo/reset", { headers });
  await ops.dispose();
});

test("4: watch a stock from its page, see it on the watchlist, remove it", async ({ page }) => {
  await signUp(page);
  await page.goto("/stocks/TITAN");
  await page.getByRole("button", { name: "☆ Watch" }).click();
  await expect(page.getByRole("button", { name: "★ Watching" })).toBeVisible();
  await page.goto("/watchlist");
  await expect(page.getByRole("link", { name: "TITAN", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Remove TITAN from watchlist" }).click();
  await expect(page.getByText("Your watchlist is empty")).toBeVisible();
});

test("5: export my data, then delete everything and end up signed out", async ({ page }) => {
  await signUp(page);
  await loadSample(page);
  await page.goto("/settings?tab=Data");
  const download = page.waitForEvent("download");
  await page.getByRole("link", { name: "Download CSV" }).click();
  expect((await download).suggestedFilename()).toBe("geotrade-ai-export.csv");
  await page.getByLabel("Type DELETE to confirm").fill("DELETE");
  await page.getByRole("button", { name: "Delete everything" }).click();
  await expect(page).toHaveURL(/\/$/);
  await page.goto("/portfolio");
  await expect(page.getByText("Sign in to see this page")).toBeVisible();
});
