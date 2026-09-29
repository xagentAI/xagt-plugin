import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";
import { SolanaProvider } from "@/components/wallet-provider";
import { AuthProvider } from "@/hooks/use-auth";
import { Toaster } from "sonner";
import { SitelinksJsonLd } from "@/components/sitelinks-json-ld";
import { Analytics } from "@vercel/analytics/next";
import { SpeedInsights } from "@vercel/speed-insights/next";
import Script from "next/script";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

import { ConfirmProvider } from "@/components/ui/custom-confirm";

export const metadata: Metadata = {
  metadataBase: new URL("https://multipu.fun"),
  title: "Multipu - Deploy Once, Launch Everywhere",
  description:
    "Multi-chain token launchpad orchestrator, real-time DEX terminal, and autonomous AI trading protocol across Solana, BNB Chain, and Robinhood Chain.",
  openGraph: {
    title: "Multipu - Deploy Once, Launch Everywhere",
    description:
      "Multi-chain token launchpad orchestrator, real-time DEX terminal, and autonomous AI trading protocol across Solana, BNB Chain, and Robinhood Chain.",
    url: "https://multipu.fun",
    siteName: "Multipu",
    images: [
      {
        url: "/og.png",
        width: 1200,
        height: 630,
        alt: "Multipu - Multi-Chain Token Orchestrator",
      },
    ],
    locale: "en_US",
    type: "website",
  },
  twitter: {
    card: "summary_large_image",
    title: "Multipu - Deploy Once, Launch Everywhere",
    description:
      "Multi-chain token launchpad orchestrator, real-time DEX terminal, and autonomous AI trading protocol.",
    images: ["/og.png"],
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <head>
        <script
          defer
          src="https://triangle-analytics.vercel.app/tracker.js"
          data-site-id="tri_819416"
        />
        <SitelinksJsonLd />
      </head>
      <body className="min-h-full flex flex-col bg-background text-foreground">
        {/* Google tag (gtag.js) */}
        <Script
          strategy="afterInteractive"
          src="https://www.googletagmanager.com/gtag/js?id=G-3YYBPW61GD"
        />
        <Script
          id="google-analytics"
          strategy="afterInteractive"
          dangerouslySetInnerHTML={{
            __html: `
              window.dataLayer = window.dataLayer || [];
              function gtag(){dataLayer.push(arguments);}
              gtag('js', new Date());
              gtag('config', 'G-3YYBPW61GD');
            `,
          }}
        />
        <SolanaProvider>
          <AuthProvider>
            <ConfirmProvider>{children}</ConfirmProvider>
          </AuthProvider>
        </SolanaProvider>
        <Toaster
          theme="dark"
          position="bottom-right"
          toastOptions={{
            style: {
              background: "rgba(15, 15, 15, 0.95)",
              border: "1px solid rgba(255,255,255,0.08)",
              color: "#e5e5e5",
              fontFamily: "var(--font-geist-mono)",
              fontSize: "13px",
            },
          }}
        />
        <Analytics />
        <SpeedInsights />
      </body>
    </html>
  );
}
