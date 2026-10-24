"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useMe } from "@/lib/auth/session";
import { NAV } from "./nav";

function Icon({ d }: { d: string }) {
  return (
    <svg viewBox="0 0 24 24" className="h-5 w-5 shrink-0" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden>
      <path d={d} strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

const active = (path: string, href: string) => (href === "/" ? path === "/" : path.startsWith(href));

/** Full sidebar on large screens, icons only on tablets, bottom tab bar on phones. */
export function Sidebar() {
  const path = usePathname();
  const { data: me } = useMe();
  const items = NAV.filter((n) => ("operator" in n ? me?.role === "operator" : !("private" in n) || Boolean(me)));
  return (
    <>
      <nav aria-label="Main" className="sticky top-0 hidden h-screen shrink-0 flex-col border-r border-line bg-surface md:flex md:w-16 lg:w-52">
        <Link href="/" className="flex h-14 items-center gap-2 px-4 font-semibold">
          <span className="rounded bg-accent px-1.5 py-0.5 text-sm text-white">GT</span>
          <span className="hidden lg:inline">GeoTrade-AI</span>
        </Link>
        <ul className="flex flex-col gap-1 p-2">
          {items.map((n) => (
            <li key={n.href}>
              <Link
                href={n.href}
                aria-current={active(path, n.href) ? "page" : undefined}
                title={n.label}
                className={`flex items-center gap-3 rounded-md px-3 py-2 text-sm ${active(path, n.href) ? "bg-accent/10 text-accent" : "text-muted hover:bg-raised hover:text-fg"}`}
              >
                <Icon d={n.icon} />
                <span className="hidden lg:inline">{n.label}</span>
              </Link>
            </li>
          ))}
        </ul>
      </nav>
      <nav aria-label="Main" className="fixed inset-x-0 bottom-0 z-40 flex border-t border-line bg-surface md:hidden">
        {items.slice(0, 5).map((n) => (
          <Link
            key={n.href}
            href={n.href}
            aria-current={active(path, n.href) ? "page" : undefined}
            className={`flex flex-1 flex-col items-center gap-0.5 py-2 text-[11px] ${active(path, n.href) ? "text-accent" : "text-muted"}`}
          >
            <Icon d={n.icon} />
            {n.label}
          </Link>
        ))}
      </nav>
    </>
  );
}
