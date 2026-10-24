import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, vi } from "vitest";
import { EmailSettings } from "@/components/digest/EmailSettings";

const prefs = {
  daily_digest_enabled: false,
  send_time_ist: "17:00",
  include_watch_ideas: true,
  include_watchlist: true,
  include_market: true,
  consented_at: null,
  unsubscribed_at: null,
  consent_text: "Send me the GeoTrade-AI Daily Pulse. It is not investment advice.",
  consent_version: "pulse-consent-v1",
  last_delivery: null,
};

afterEach(() => vi.unstubAllGlobals());

describe("EmailSettings", () => {
  it("asks for consent before the Daily Pulse can be turned on", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(prefs), { status: 200, headers: { "Content-Type": "application/json" } })));
    render(
      <QueryClientProvider client={new QueryClient()}>
        <EmailSettings />
      </QueryClientProvider>,
    );
    fireEvent.click(await screen.findByLabelText("Send me the Daily Pulse"));
    expect(screen.getByText(/not investment advice/)).toBeInTheDocument();
    const save = screen.getByRole("button", { name: "Save" });
    expect(save).toBeDisabled();
    fireEvent.click(screen.getByRole("checkbox", { name: /Send me the GeoTrade-AI Daily Pulse/ }));
    expect(save).toBeEnabled();
  });
});
