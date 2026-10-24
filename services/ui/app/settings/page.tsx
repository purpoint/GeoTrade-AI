"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { EmailSettings } from "@/components/digest/EmailSettings";
import { RequireAuth } from "@/components/RequireAuth";
import { buildUrl, post, type Me } from "@/lib/api/client";
import { useAuthActions, useMe } from "@/lib/auth/session";

const TABS = ["Profile", "Preferences", "Email", "Data"] as const;
const input = "mt-1 w-full rounded border border-line bg-surface px-2 py-1.5 text-sm text-fg";

function Saved({ msg }: { msg: string | null }) {
  return msg ? (
    <p className="text-xs text-muted" role="status">
      {msg}
    </p>
  ) : null;
}

function Profile({ me }: { me: Me }) {
  const qc = useQueryClient();
  const [name, setName] = useState(me.display_name ?? "");
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const save = async (fn: () => Promise<Me>, ok: string) => {
    try {
      qc.setQueryData(["me"], await fn());
      setMsg(ok);
    } catch (e) {
      setMsg(e instanceof Error ? e.message : "Could not save");
    }
  };
  return (
    <div className="space-y-4">
      <form className="card space-y-2 p-4" onSubmit={(e) => (e.preventDefault(), void save(() => post<Me>("/me", { display_name: name }, "PATCH"), "Name saved"))}>
        <p className="text-sm text-muted">Signed in as {me.email}</p>
        <label className="block text-xs text-muted">
          Display name
          <input value={name} onChange={(e) => setName(e.target.value)} className={input} maxLength={80} />
        </label>
        <button className="rounded bg-accent px-3 py-1 text-sm text-on-accent">Save</button>
      </form>
      {!me.is_demo ? (
        <form
          className="card space-y-2 p-4"
          onSubmit={(e) => {
            e.preventDefault();
            void save(() => post<Me>("/me/password", { current_password: current, new_password: next }), "Password changed; other sessions were signed out");
            setCurrent("");
            setNext("");
          }}
        >
          <h2 className="text-sm font-semibold">Change password</h2>
          <input type="password" placeholder="Current password" value={current} onChange={(e) => setCurrent(e.target.value)} className={input} autoComplete="current-password" required />
          <input type="password" placeholder="New password (10+ characters)" value={next} onChange={(e) => setNext(e.target.value)} className={input} autoComplete="new-password" minLength={10} required />
          <button className="rounded border border-line px-3 py-1 text-sm hover:bg-raised">Change password</button>
        </form>
      ) : null}
      <Saved msg={msg} />
    </div>
  );
}

function Preferences({ me }: { me: Me }) {
  const qc = useQueryClient();
  const prefs = me.preferences as { quiet_hours?: { start: string; end: string }; alerts_enabled?: boolean };
  const [quiet, setQuiet] = useState(Boolean(prefs.quiet_hours));
  const [start, setStart] = useState(prefs.quiet_hours?.start ?? "22:00");
  const [end, setEnd] = useState(prefs.quiet_hours?.end ?? "07:00");
  const [alerts, setAlerts] = useState(prefs.alerts_enabled !== false);
  const [msg, setMsg] = useState<string | null>(null);
  return (
    <form
      className="card space-y-3 p-4 text-sm"
      onSubmit={async (e) => {
        e.preventDefault();
        try {
          const body = { preferences: { alerts_enabled: alerts, ...(quiet ? { quiet_hours: { start, end } } : {}) } };
          qc.setQueryData(["me"], await post<Me>("/me", body, "PATCH"));
          setMsg("Preferences saved");
        } catch (err) {
          setMsg(err instanceof Error ? err.message : "Could not save");
        }
      }}
    >
      <label className="flex items-center gap-2">
        <input type="checkbox" checked={alerts} onChange={(e) => setAlerts(e.target.checked)} /> Send me alerts about my holdings
      </label>
      <label className="flex items-center gap-2">
        <input type="checkbox" checked={quiet} onChange={(e) => setQuiet(e.target.checked)} /> Quiet hours (alerts still arrive, without a live pop-up)
      </label>
      {quiet ? (
        <div className="flex gap-2">
          <label className="text-xs text-muted">
            From (IST)
            <input type="time" value={start} onChange={(e) => setStart(e.target.value)} className={input} />
          </label>
          <label className="text-xs text-muted">
            To (IST)
            <input type="time" value={end} onChange={(e) => setEnd(e.target.value)} className={input} />
          </label>
        </div>
      ) : null}
      <p className="text-xs text-muted">Attention weights are set from the Needs Attention page.</p>
      <button className="rounded bg-accent px-3 py-1 text-on-accent">Save</button>
      <Saved msg={msg} />
    </form>
  );
}

function Data({ me }: { me: Me }) {
  const { logout } = useAuthActions();
  const [typed, setTyped] = useState("");
  const [error, setError] = useState<string | null>(null);
  return (
    <div className="space-y-4 text-sm">
      <section className="card space-y-2 p-4">
        <h2 className="font-semibold">Export</h2>
        <p className="text-muted">Download everything stored about you: profile, preferences, holdings, watchlist, alert rules, alerts, email preferences and digest history.</p>
        <a href={buildUrl("/me/export")} className="inline-block rounded border border-line px-3 py-1 hover:bg-raised" download>
          Download CSV
        </a>
      </section>
      {!me.is_demo ? (
        <section className="card space-y-2 border-neg/40 p-4">
          <h2 className="font-semibold text-neg">Delete my data</h2>
          <p className="text-muted">This permanently deletes your account and every holding, alert and setting. It cannot be undone.</p>
          <label className="block text-xs text-muted">
            Type DELETE to confirm
            <input value={typed} onChange={(e) => setTyped(e.target.value)} className={input} />
          </label>
          <button
            disabled={typed !== "DELETE"}
            onClick={async () => {
              try {
                await post("/me", { confirm: true }, "DELETE");
                await logout();
              } catch (e) {
                setError(e instanceof Error ? e.message : "Could not delete");
              }
            }}
            className="rounded bg-neg px-3 py-1 text-on-accent disabled:opacity-40"
          >
            Delete everything
          </button>
          {error ? <p className="text-neg">{error}</p> : null}
        </section>
      ) : null}
    </div>
  );
}

export default function SettingsPage() {
  const { data: me } = useMe();
  const [tab, setTab] = useState<(typeof TABS)[number]>("Profile");
  useEffect(() => {
    const t = new URLSearchParams(window.location.search).get("tab")?.toLowerCase();
    const match = TABS.find((x) => x.toLowerCase() === t);
    if (match) setTab(match);
  }, []);
  return (
    <RequireAuth>
      <div className="mx-auto max-w-2xl space-y-4">
        <h1 className="text-xl font-semibold">Settings</h1>
        <div role="tablist" className="flex gap-1 border-b border-line">
          {TABS.map((t) => (
            <button key={t} role="tab" aria-selected={tab === t} onClick={() => setTab(t)} className={`px-3 py-1.5 text-sm ${tab === t ? "border-b-2 border-accent text-fg" : "text-muted"}`}>
              {t}
            </button>
          ))}
        </div>
        {me ? tab === "Profile" ? <Profile me={me} /> : tab === "Preferences" ? <Preferences me={me} /> : tab === "Email" ? <EmailSettings /> : <Data me={me} /> : null}
      </div>
    </RequireAuth>
  );
}
