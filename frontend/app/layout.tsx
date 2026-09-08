import type { Metadata } from "next";
import Nav from "./components/Nav";
import { ModeProvider } from "./lib/mode";
import "./globals.css";

export const metadata: Metadata = {
  title: "Airline Operations Lab",
  description:
    "US airline on-time performance, 2018-present, sourced directly from the DOT Bureau of Transportation Statistics. Carrier comparisons, delay trends, and coded delay causes.",
  openGraph: {
    title: "Airline On-Time Performance",
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
        <ModeProvider>
          <div className="ambient-backdrop" aria-hidden="true">
            <span className="ambient-orb ambient-orb-one" />
            <span className="ambient-orb ambient-orb-two" />
            <span className="ambient-grid" />
          </div>
          <Nav />
          {children}
        </ModeProvider>
      </body>
    </html>
  );
}
