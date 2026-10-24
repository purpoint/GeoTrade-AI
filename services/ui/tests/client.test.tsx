import { afterEach, vi } from "vitest";
import { api, ApiError, csrfToken, post } from "@/lib/api/client";

const json = (status: number, body: unknown) =>
  new Response(status === 204 ? null : JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

afterEach(() => {
  vi.unstubAllGlobals();
  document.cookie = "gt_csrf=; expires=Thu, 01 Jan 1970 00:00:00 GMT";
});

describe("api client", () => {
  it("reads the CSRF cookie and sends it on mutations only", async () => {
    document.cookie = "gt_csrf=abc123";
    expect(csrfToken()).toBe("abc123");
    const calls: RequestInit[] = [];
    vi.stubGlobal("fetch", vi.fn(async (_url: string, init: RequestInit) => (calls.push(init), json(200, { ok: true }))));
    await api("/stocks");
    await post("/watchlist/INFY", undefined, "PUT");
    expect((calls[0]!.headers as Record<string, string>)["X-CSRF-Token"]).toBeUndefined();
    expect((calls[1]!.headers as Record<string, string>)["X-CSRF-Token"]).toBe("abc123");
  });

  it("refreshes once on 401 and retries", async () => {
    const urls: string[] = [];
    let first = true;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        urls.push(url);
        if (url.endsWith("/auth/refresh")) return json(200, {});
        if (first) return (first = false), json(401, { error: { code: "unauthorized", message: "x" } });
        return json(200, { id: 1 });
      }),
    );
    expect(await api<{ id: number }>("/me")).toEqual({ id: 1 });
    expect(urls).toEqual(["/api/v1/me", "/api/v1/auth/refresh", "/api/v1/me"]);
  });

  it("surfaces the API error envelope", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => json(409, { error: { code: "email_taken", message: "taken" } })));
    await expect(post("/auth/signup", {})).rejects.toEqual(new ApiError(409, "email_taken", "taken"));
  });
});
