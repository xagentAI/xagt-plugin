import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // ─── Turbopack Configuration ────────────────────────
  turbopack: {
    root: __dirname,
  },

  // ─── Security Headers ──────────────────────────────
  async headers() {
    return [
      {
        source: "/(.*)",
        headers: [
          { key: "X-Frame-Options", value: "DENY" },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
          {
            key: "Strict-Transport-Security",
            value: "max-age=63072000; includeSubDomains; preload",
          },
          {
            key: "Content-Security-Policy",
            value: [
              "default-src 'self'",
              "script-src 'self' 'unsafe-eval' 'unsafe-inline' https://triangle-analytics.vercel.app https://www.googletagmanager.com",
              "style-src 'self' 'unsafe-inline'",
              "img-src 'self' blob: data: https:",
              "font-src 'self' https://fonts.gstatic.com",
              "frame-src 'self' https://dexscreener.com https://*.dexscreener.com https://*.tradingview.com",
              "child-src 'self' https://dexscreener.com https://*.dexscreener.com",
              "connect-src 'self' https://triangle-analytics.vercel.app https://*.google-analytics.com https://*.supabase.co https://*.helius-rpc.com https://api.devnet.solana.com https://api.mainnet-beta.solana.com wss://*.solana.com https://*.dexscreener.com https://api.dexscreener.com https://quote-api.jup.ag https://*.jup.ag",
              "frame-ancestors 'none'",
              "base-uri 'self'",
              "form-action 'self'",
            ].join("; "),
          },
        ],
      },
    ];
  },

  // ─── Image Domains ─────────────────────────────────
  images: {
    remotePatterns: [
      { protocol: "https", hostname: "cdn.dexscreener.com" },
      { protocol: "https", hostname: "dd.dexscreener.com" },
      { protocol: "https", hostname: "arweave.net" },
      { protocol: "https", hostname: "**.ipfs.dweb.link" },
      { protocol: "https", hostname: "raw.githubusercontent.com" },
      { protocol: "https", hostname: "assets.coingecko.com" },
      { protocol: "https", hostname: "coin-images.coingecko.com" },
      { protocol: "https", hostname: "ipfs.io" },
      { protocol: "https", hostname: "gateway.pinata.cloud" },
      { protocol: "https", hostname: "cf-ipfs.com" },
      { protocol: "https", hostname: "pump.fun" },
      { protocol: "https", hostname: "api.dicebear.com" },
      { protocol: "https", hostname: "images.unsplash.com" },
    ],
  },

  // ─── Performance ───────────────────────────────────
  poweredByHeader: false,
};

export default nextConfig;
