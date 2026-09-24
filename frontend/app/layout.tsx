import type { Metadata } from "next";
import { Suspense } from "react";
import { AppShell } from "./components/product/AppShell";
import "./globals.css";
import "./product.css";
import "./product-extensions.css";

export const metadata: Metadata = {
  title: "Airline Operations Intelligence",
  description:
    "US airline on-time performance, 2018-present, sourced directly from the DOT Bureau of Transportation Statistics. Carrier comparisons, delay trends, and coded delay causes.",
  openGraph: {
    title: "Airline Operations Intelligence",
    description: "US airline on-time performance, 2018-present, from DOT/BTS data.",
    type: "website",
  },
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>
        <Suspense fallback={<main className="app-loading-shell">Opening Airline Operations Intelligence…</main>}>
          <AppShell>{children}</AppShell>
        </Suspense>
      </body>
    </html>
  );
}
