import type { Metadata } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";
import { AppShell } from "@/components/shell/AppShell";
import { THEME_SCRIPT } from "@/components/shell/ThemeToggle";
import { Providers } from "./providers";
import "./globals.css";

const sans = Inter({ subsets: ["latin"], variable: "--font-sans", display: "swap" });
const mono = JetBrains_Mono({ subsets: ["latin"], variable: "--font-mono", display: "swap" });

export const metadata: Metadata = {
  title: { default: "GeoTrade-AI", template: "%s · GeoTrade-AI" },
  description: "NIFTY 50 news sentiment, events and prices. Not investment advice.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${sans.variable} ${mono.variable}`} suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_SCRIPT }} />
      </head>
      <body>
        <Providers>
          <AppShell>{children}</AppShell>
        </Providers>
      </body>
    </html>
  );
}
