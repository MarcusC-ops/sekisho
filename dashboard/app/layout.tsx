import type { Metadata } from "next";
import "@fontsource-variable/atkinson-hyperlegible-next";
import "@fontsource-variable/atkinson-hyperlegible-mono";
import "./tokens.css";
import "./globals.css";
import { AppShell } from "@/components/shell/AppShell";
import { Providers } from "./providers";

export const metadata: Metadata = {
  title: {
    default: "Sekisho Compliance Console",
    template: "%s · Sekisho",
  },
  description:
    "Live compliance decisions for AI agent payments: every counterparty screened before the agent signs, held for a human or blocked, and attested onchain.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>
        <Providers>
          <AppShell>{children}</AppShell>
        </Providers>
      </body>
    </html>
  );
}
