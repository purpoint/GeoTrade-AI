"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { useAuthActions, useMe } from "@/lib/auth/session";

export function UserMenu() {
  const { data: me } = useMe();
  const { logout } = useAuthActions();
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const close = (e: MouseEvent) => box.current && !box.current.contains(e.target as Node) && setOpen(false);
    document.addEventListener("click", close);
    return () => document.removeEventListener("click", close);
  }, []);
  if (!me)
    return (
      <Link href="/login" className="rounded-md bg-accent px-2.5 py-1 text-xs text-white">
        Sign in
      </Link>
    );
  const initial = (me.display_name || me.email).slice(0, 1).toUpperCase();
  return (
    <div className="relative" ref={box}>
      <button onClick={() => setOpen((o) => !o)} aria-expanded={open} aria-haspopup="menu" aria-label="Account menu" className="flex h-7 w-7 items-center justify-center rounded-full bg-accent text-xs font-medium text-white">
        {initial}
      </button>
      {open ? (
        <div role="menu" className="card absolute right-0 top-9 z-40 w-48 py-1 text-sm shadow-lg">
          <p className="truncate px-3 py-1 text-xs text-muted">{me.is_demo ? "Demo account" : me.email}</p>
          {[
            ["/portfolio", "Portfolio"],
            ["/settings", "Settings"],
            ...(me.role === "operator" ? [["/admin", "Operator console"]] : []),
          ].map(([href, label]) => (
            <Link key={href} role="menuitem" href={href as string} onClick={() => setOpen(false)} className="block px-3 py-1.5 hover:bg-raised">
              {label}
            </Link>
          ))}
          <button role="menuitem" onClick={() => void logout()} className="block w-full px-3 py-1.5 text-left hover:bg-raised">
            Sign out
          </button>
        </div>
      ) : null}
    </div>
  );
}
