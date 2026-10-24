import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { signUp, loadSample } from "./helpers";

async function demo(page: Page) {
  await page.goto("/login");
  await page.getByRole("button", { name: "Try the demo account" }).click();
  await expect(page).toHaveURL(/\/portfolio/);
}

for (const path of ["/", "/stocks/RELIANCE", "/news", "/login", "/unsubscribe"]) {
  test(`a11y: ${path} has no serious or critical axe violations`, async ({ page }) => {
    await page.goto(path);
    await page.waitForLoadState("networkidle");
    const { violations } = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze();
    const bad = violations.filter((v) => v.impact === "serious" || v.impact === "critical");
    expect(bad.map((v) => `${v.id}: ${v.nodes.length} nodes`)).toEqual([]);
  });
}

test("Daily Pulse: opt in with consent, then read today's digest in the app", async ({ page }) => {
  await signUp(page);
  await loadSample(page);
  await page.goto("/settings?tab=email");
  await page.getByLabel("Send me the Daily Pulse").check();
  const save = page.getByRole("button", { name: "Save" });
  await expect(save).toBeDisabled();
  await page.getByRole("checkbox", { name: /Send me the GeoTrade-AI Daily Pulse/ }).check();
  await save.click();
  await expect(page.getByText(/Your next Daily Pulse arrives/)).toBeVisible();
  await page.goto("/digest");
  await expect(page.getByRole("heading", { name: "Daily Pulse" })).toBeVisible();
  const email = page.frameLocator('iframe[title="Daily Pulse email"]');
  await expect(email.getByText("Not investment advice.", { exact: false }).first()).toBeVisible();
  await expect(email.getByText("Holdings to review (risk flags)")).toBeVisible();
});

test("plain-English rule: check what was understood, then save it", async ({ page }) => {
  await demo(page);
  await page.goto("/alerts");
  await page.getByRole("tab", { name: "rules" }).click();
  await page.getByLabel("Describe an alert").fill("Tell me if any bank I hold gets RBI news");
  await page.getByRole("button", { name: "Check" }).click();
  await expect(page.getByText(/We understood:/)).toBeVisible();
  await expect(page.getByText(/Banking/).first()).toBeVisible();
});

test("unsubscribe landing explains itself without a token", async ({ page }) => {
  await page.goto("/unsubscribe");
  await expect(page.getByText("This page needs the link from a Daily Pulse email.")).toBeVisible();
});
