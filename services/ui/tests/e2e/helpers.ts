import { expect, type APIRequestContext, type Page } from "@playwright/test";

export const PASSWORD = "e2e-correct-horse-battery";

export const uniqueEmail = () => `e2e-${Date.now()}-${Math.random().toString(36).slice(2, 8)}@example.com`;

export async function signUp(page: Page, email = uniqueEmail()): Promise<string> {
  await page.goto("/signup");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("checkbox").check();
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page).toHaveURL(/\/onboarding/);
  return email;
}

export async function loadSample(page: Page) {
  await page.getByRole("button", { name: "Load sample" }).click();
  await page.getByRole("button", { name: "Go to my portfolio" }).click();
  await expect(page.getByRole("heading", { name: "Portfolio", exact: true })).toBeVisible();
}

/** Operator session over the API; null when the stack has no operator account configured. */
export async function operator(request: APIRequestContext): Promise<{ csrf: string } | null> {
  const email = process.env.E2E_OPERATOR_EMAIL;
  const password = process.env.E2E_OPERATOR_PASSWORD;
  if (!email || !password) return null;
  const r = await request.post("/api/v1/auth/login", { data: { email, password } });
  if (!r.ok()) return null;
  const cookie = (await request.storageState()).cookies.find((c) => c.name === "gt_csrf");
  return { csrf: cookie?.value ?? "" };
}
