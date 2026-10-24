import { expect, test } from "@playwright/test";

// Needs the stack up with seeded data: docker compose up, then `npm run e2e`.
test("overview loads, open a stock, open an article", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Market overview" })).toBeVisible();
  await page.goto("/stocks/INFY");
  await expect(page.getByRole("heading", { level: 1, name: /Infosys/ })).toBeVisible();
  await page.goto("/news");
  const first = page.locator("article h3 a").first();
  await expect(first).toBeVisible();
  await first.click();
  await expect(page.getByRole("heading", { name: "How we scored this" })).toBeVisible();
});
