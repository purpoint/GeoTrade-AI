export const NAV = [
  { href: "/", label: "Overview", icon: "M3 12l9-9 9 9M5 10v10h14V10" },
  { href: "/stocks", label: "Stocks", icon: "M4 19V9m6 10V5m6 14v-7m4 7H2" },
  { href: "/sectors", label: "Sectors", icon: "M4 4h7v7H4zM13 4h7v7h-7zM4 13h7v7H4zM13 13h7v7h-7z" },
  { href: "/news", label: "News", icon: "M4 5h16v14H4zM8 9h8M8 13h8M8 17h5" },
  { href: "/portfolio", label: "Portfolio", icon: "M3 7h18v13H3zM8 7V4h8v3", private: true },
  { href: "/attention", label: "Attention", icon: "M12 9v4m0 4h.01M10.3 3.9L2.2 18a2 2 0 001.7 3h16.2a2 2 0 001.7-3L13.7 3.9a2 2 0 00-3.4 0z", private: true },
  { href: "/alerts", label: "Alerts", icon: "M6 16V11a6 6 0 1112 0v5l1.5 2h-15zM10 20a2 2 0 004 0", private: true },
  { href: "/watchlist", label: "Watchlist", icon: "M12 3l2.7 5.6 6.3.9-4.5 4.4 1 6.1L12 17l-5.5 3 1-6.1L3 9.5l6.3-.9z", private: true },
  { href: "/methodology", label: "Method", icon: "M12 3a9 9 0 100 18 9 9 0 000-18zm0 5v5m0 3h.01" },
  { href: "/admin/demo", label: "Demo", icon: "M5 3l14 9-14 9V3z" },
] as const satisfies readonly { href: string; label: string; icon: string; private?: boolean }[];
