import type { Metadata } from "next";
import { Instrument_Sans, Instrument_Serif } from "next/font/google";
import "./globals.css";
import { Providers } from "./providers";

// Display face — headings only. Instrument Serif ships a single weight.
const instrumentSerif = Instrument_Serif({
  weight: "400",
  style: ["normal", "italic"],
  subsets: ["latin"],
  display: "swap",
  variable: "--font-instrument-serif",
});

// UI/body face. Consumed through `--font-sans` in globals.css, which
// Tailwind's preflight applies to the whole document.
const instrumentSans = Instrument_Sans({
  weight: ["400", "500", "600", "700"],
  subsets: ["latin"],
  display: "swap",
  variable: "--font-instrument-sans",
});

export const metadata: Metadata = {
  title: "Arcway — Stablecoin payouts by email",
  description:
    "Arcway pays your contractors and remote staff in USDC using nothing but their email address. No wallets to collect, no correspondent banks.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html
      lang="en"
      className={`${instrumentSans.variable} ${instrumentSerif.variable}`}
    >
      <body className="min-h-screen antialiased">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
