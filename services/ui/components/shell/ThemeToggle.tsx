"use client";

import { useCallback, useEffect, useState } from "react";

type Theme = "light" | "dark";

function readTheme(): Theme {
  return document.documentElement.dataset.theme === "dark" ? "dark" : "light";
}

export function useTheme() {
  const [theme, setTheme] = useState<Theme>("light");
  useEffect(() => setTheme(readTheme()), []);
  const toggle = useCallback(() => {
    const next: Theme = readTheme() === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try {
      localStorage.setItem("theme", next);
    } catch {
      /* private mode: theme just won't persist */
    }
    setTheme(next);
  }, []);
  return { theme, toggle };
}

export function ThemeToggle({ theme, toggle }: { theme: Theme; toggle: () => void }) {
  return (
    <button
      onClick={toggle}
      className="rounded-md border border-line px-2 py-1 text-xs text-muted hover:bg-raised"
      aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} theme (shortcut t)`}
      title="Theme (t)"
    >
      {theme === "dark" ? "☀ Light" : "☾ Dark"}
    </button>
  );
}

/** Runs before paint so the saved or system theme applies without a flash. */
export const THEME_SCRIPT = `try{var t=localStorage.getItem("theme")||(matchMedia("(prefers-color-scheme: dark)").matches?"dark":"light");document.documentElement.dataset.theme=t}catch(e){}`;
