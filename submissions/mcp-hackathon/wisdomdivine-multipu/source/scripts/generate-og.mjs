import fs from "fs";
import path from "path";
import { Resvg } from "@resvg/resvg-js";
import sharp from "sharp";

async function generateOgImage() {
  const width = 1200;
  const height = 630;

  // Load official Multipu 3D logo
  const logoPath = path.join(process.cwd(), "public", "logo.png");
  const logoBase64 = fs.readFileSync(logoPath).toString("base64");
  const logoDataUri = `data:image/png;base64,${logoBase64}`;

  const svg = `
<svg width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <!-- Ambient Radial Glows -->
    <radialGradient id="purpleAura" cx="72%" cy="40%" r="52%">
      <stop offset="0%" stop-color="#8b5cf6" stop-opacity="0.17"/>
      <stop offset="50%" stop-color="#6366f1" stop-opacity="0.06"/>
      <stop offset="100%" stop-color="#0a0b0e" stop-opacity="0"/>
    </radialGradient>

    <!-- Neon Pulse Glow -->
    <filter id="neonGlow" x="-50%" y="-50%" width="200%" height="200%">
      <feGaussianBlur stdDeviation="3.5" result="blur"/>
      <feMerge>
        <feMergeNode in="blur"/>
        <feMergeNode in="blur"/>
        <feMergeNode in="SourceGraphic"/>
      </feMerge>
    </filter>

    <filter id="cardShadow" x="-30%" y="-30%" width="160%" height="160%">
      <feDropShadow dx="-8" dy="16" stdDeviation="18" flood-color="#000000" flood-opacity="0.92"/>
    </filter>

    <!-- Dot Matrix Grid Pattern -->
    <pattern id="dotGrid" width="28" height="28" patternUnits="userSpaceOnUse">
      <circle cx="2" cy="2" r="1.1" fill="rgba(255, 255, 255, 0.055)"/>
    </pattern>

    <!-- Card Backgrounds -->
    <linearGradient id="cardBg" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#141520"/>
      <stop offset="100%" stop-color="#0e0f17"/>
    </linearGradient>

    <linearGradient id="cardBgActive" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#181a27"/>
      <stop offset="100%" stop-color="#10121c"/>
    </linearGradient>

    <!-- Solana Gradient -->
    <linearGradient id="solGrad" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#9945ff"/>
      <stop offset="100%" stop-color="#14f195"/>
    </linearGradient>
  </defs>

  <!-- 1. Background Base -->
  <rect width="${width}" height="${height}" fill="#0a0b0e"/>

  <!-- 2. Ambient Color Auras -->
  <rect width="${width}" height="${height}" fill="url(#purpleAura)"/>

  <!-- 3. Dot Grid Texture -->
  <rect width="${width}" height="${height}" fill="url(#dotGrid)"/>

  <!-- ═════════════════════════════════════════════════════════ -->
  <!-- LEFT BRANDING & TYPOGRAPHY -->
  <!-- ═════════════════════════════════════════════════════════ -->

  <!-- Top-Left Logo + Brand -->
  <g transform="translate(80, 72)">
    <image href="${logoDataUri}" x="0" y="0" width="44" height="44" preserveAspectRatio="xMidYMid meet"/>
    <text x="56" y="32" fill="#ffffff" font-size="32" font-weight="700" font-family="system-ui, -apple-system, sans-serif" letter-spacing="-0.5">Multipu</text>
  </g>

  <!-- Bottom-Left Massive Bold Headline: SHIP WITHOUT FRICTION style -->
  <g transform="translate(80, 380)">
    <text x="0" y="0" fill="#ffffff" font-size="78" font-weight="900" font-family="system-ui, -apple-system, sans-serif" letter-spacing="-2.8">LAUNCH</text>
    <text x="0" y="80" fill="#ffffff" font-size="78" font-weight="900" font-family="system-ui, -apple-system, sans-serif" letter-spacing="-2.8">WITHOUT</text>
    <text x="0" y="160" fill="#ffffff" font-size="78" font-weight="900" font-family="system-ui, -apple-system, sans-serif" letter-spacing="-2.8">FRICTION</text>
  </g>

  <!-- ═════════════════════════════════════════════════════════ -->
  <!-- RIGHT SIDE: ISOMETRIC INTERCONNECTED 3D ARCHITECTURE -->
  <!-- ═════════════════════════════════════════════════════════ -->

  <g transform="translate(450, 270) rotate(-24) skewX(29)">

    <!-- ── TRACES ON ISOMETRIC GRID ── -->
    <!-- Trace 1: Orchestrator -> Solana Engine -->
    <path d="M 220 0 L 220 -80 L 350 -80" fill="none" stroke="#7c3aed" stroke-width="3.5" opacity="0.3" filter="url(#neonGlow)"/>
    <path d="M 220 0 L 220 -80 L 350 -80" fill="none" stroke="#c084fc" stroke-width="1.8" stroke-dasharray="6 4"/>
    
    <circle cx="220" cy="-35" r="5" fill="#f43f5e" filter="url(#neonGlow)"/>
    <circle cx="220" cy="-35" r="2.5" fill="#ffffff"/>

    <circle cx="220" cy="-80" r="5.5" fill="#ec4899" filter="url(#neonGlow)"/>
    <circle cx="220" cy="-80" r="2.5" fill="#ffffff"/>

    <circle cx="350" cy="-80" r="5" fill="#a855f7" filter="url(#neonGlow)"/>
    <circle cx="350" cy="-80" r="2.5" fill="#ffffff"/>

    <!-- Trace 2: Orchestrator -> Trading Terminal -->
    <path d="M 180 160 L 180 225" fill="none" stroke="#7c3aed" stroke-width="3.5" opacity="0.3" filter="url(#neonGlow)"/>
    <path d="M 180 160 L 180 225" fill="none" stroke="#a855f7" stroke-width="1.8" stroke-dasharray="6 4"/>
    
    <circle cx="180" cy="192" r="5" fill="#c084fc" filter="url(#neonGlow)"/>
    <circle cx="180" cy="192" r="2.5" fill="#ffffff"/>

    <!-- Trace 3: Solana Engine -> Four.meme -->
    <path d="M 500 -10 L 500 90 L 440 90" fill="none" stroke="#7c3aed" stroke-width="3" opacity="0.25" filter="url(#neonGlow)"/>
    <path d="M 500 -10 L 500 90 L 440 90" fill="none" stroke="#e879f9" stroke-width="1.5" stroke-dasharray="6 4"/>

    <circle cx="500" cy="40" r="4.5" fill="#38bdf8" filter="url(#neonGlow)"/>
    <circle cx="500" cy="40" r="2" fill="#ffffff"/>

    <!-- ── CARD 5: BACKGROUND PEEKING FOLDER ── -->
    <g transform="translate(300, -170)">
      <rect x="0" y="0" width="240" height="110" rx="14" fill="#0d0e14" stroke="rgba(255,255,255,0.06)" stroke-width="1.2"/>
      <path d="M 22 28 L 32 28 L 36 32 L 50 32 L 50 44 L 22 44 Z" fill="none" stroke="#475569" stroke-width="1.8"/>
      <text x="58" y="38" fill="#475569" font-size="13" font-weight="600" font-family="system-ui, sans-serif">Deployment Packs</text>
    </g>

    <!-- ── CARD 4: TOP FAR RIGHT (Four.meme - BNB Chain) ── -->
    <g transform="translate(390, 90)">
      <rect x="0" y="0" width="290" height="150" rx="16" fill="url(#cardBg)" stroke="rgba(255,255,255,0.12)" stroke-width="1.2" filter="url(#cardShadow)"/>
      
      <!-- BNB Icon -->
      <rect x="22" y="24" width="28" height="28" rx="7" fill="#f3ba2f"/>
      <path d="M 36 30 L 41 35 L 36 40 L 31 35 Z M 36 34 L 38 36 L 36 38 L 34 36 Z" fill="#1e2026"/>
      
      <!-- Title -->
      <text x="60" y="44" fill="#ffffff" font-size="17" font-weight="700" font-family="system-ui, sans-serif">Four.meme</text>
      
      <!-- Checkmark & Status -->
      <circle cx="28" cy="85" r="7.5" fill="none" stroke="#10b981" stroke-width="1.8"/>
      <path d="M 25 85 L 27.5 87.5 L 31.5 83" fill="none" stroke="#10b981" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
      <text x="44" y="89" fill="#94a3b8" font-size="13" font-family="system-ui, sans-serif">Just now via BNB Chain</text>

      <!-- Bottom Liquidity metadata -->
      <rect x="22" y="110" width="125" height="22" rx="5" fill="rgba(243, 186, 47, 0.08)"/>
      <text x="30" y="125" fill="#fbbf24" font-size="11" font-weight="600" font-family="monospace">500 BNB Liquidity</text>
    </g>

    <!-- ── CARD 3: TOP CENTER (Solana Engine / Pump.fun & Meteora) ── -->
    <g transform="translate(350, -90)">
      <rect x="0" y="0" width="300" height="155" rx="16" fill="url(#cardBgActive)" stroke="rgba(255,255,255,0.16)" stroke-width="1.2" filter="url(#cardShadow)"/>
      
      <!-- Solana Icon Badge -->
      <rect x="22" y="24" width="28" height="28" rx="7" fill="url(#solGrad)"/>
      <path d="M 28 32 L 44 32 M 28 38 L 44 38 M 28 44 L 44 44" stroke="#ffffff" stroke-width="2" stroke-linecap="round"/>
      
      <!-- Title -->
      <text x="60" y="44" fill="#ffffff" font-size="17" font-weight="700" font-family="system-ui, sans-serif">Solana Engine</text>
      
      <!-- Checkmark & Status -->
      <circle cx="28" cy="85" r="7.5" fill="none" stroke="#10b981" stroke-width="1.8"/>
      <path d="M 25 85 L 27.5 87.5 L 31.5 83" fill="none" stroke="#10b981" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
      <text x="44" y="89" fill="#94a3b8" font-size="13" font-family="system-ui, sans-serif">Pump.fun Bonding Curve</text>

      <!-- Subtitle metadata like /bitnami -->
      <g transform="translate(22, 114)">
        <rect x="0" y="0" width="16" height="16" rx="4" fill="rgba(168, 85, 247, 0.15)"/>
        <circle cx="8" cy="8" r="3" fill="#c084fc"/>
        <text x="24" y="12" fill="#a78bfa" font-size="11.5" font-weight="500" font-family="monospace">Raydium DLMM / 0.5%</text>
      </g>
    </g>

    <!-- ── CARD 1: CENTER HUB (Token Orchestrator) ── -->
    <g transform="translate(0, 0)">
      <rect x="0" y="0" width="330" height="160" rx="18" fill="url(#cardBgActive)" stroke="rgba(255,255,255,0.18)" stroke-width="1.3" filter="url(#cardShadow)"/>
      
      <!-- Official Logo in Card -->
      <image href="${logoDataUri}" x="22" y="24" width="28" height="28" preserveAspectRatio="xMidYMid meet"/>
      
      <!-- Title -->
      <text x="60" y="44" fill="#ffffff" font-size="18" font-weight="700" font-family="system-ui, sans-serif">Token Orchestrator</text>
      
      <!-- Sub-label -->
      <text x="24" y="76" fill="#94a3b8" font-size="13" font-family="system-ui, sans-serif">Solana · BNB Chain · Robinhood</text>

      <!-- Checkmark & Status -->
      <circle cx="28" cy="110" r="7.5" fill="none" stroke="#10b981" stroke-width="1.8"/>
      <path d="M 25 110 L 27.5 112.5 L 31.5 108" fill="none" stroke="#10b981" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
      <text x="44" y="114" fill="#34d399" font-size="13" font-weight="600" font-family="system-ui, sans-serif">1-Click Multi-Chain Dispatch</text>

      <!-- Live Block status badge -->
      <rect x="22" y="130" width="125" height="20" rx="5" fill="rgba(255,255,255,0.06)"/>
      <circle cx="32" cy="140" r="3.5" fill="#10b981"/>
      <text x="42" y="144" fill="#e2e8f0" font-size="10" font-weight="600" font-family="monospace">MAINNET VERIFIED</text>
    </g>

    <!-- ── CARD 2: BOTTOM RIGHT (Trading Terminal) ── -->
    <g transform="translate(0, 225)">
      <rect x="0" y="0" width="330" height="160" rx="18" fill="url(#cardBg)" stroke="rgba(255,255,255,0.14)" stroke-width="1.2" filter="url(#cardShadow)"/>
      
      <!-- Terminal / Signals Icon -->
      <rect x="22" y="24" width="28" height="28" rx="7" fill="#8b5cf6"/>
      <path d="M 29 32 L 34 38 L 29 44 M 35 44 L 43 44" stroke="#ffffff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
      
      <!-- Title & Purple URL exactly like Railway -->
      <text x="60" y="44" fill="#ffffff" font-size="18" font-weight="700" font-family="system-ui, sans-serif">Trading Terminal</text>
      
      <text x="24" y="76" fill="#c084fc" font-size="13" font-weight="600" font-family="monospace">terminal.multipu.fun</text>
      
      <!-- Checkmark & Status -->
      <circle cx="28" cy="110" r="7.5" fill="none" stroke="#10b981" stroke-width="1.8"/>
      <path d="M 25 110 L 27.5 112.5 L 31.5 108" fill="none" stroke="#10b981" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
      <text x="44" y="114" fill="#94a3b8" font-size="13" font-family="system-ui, sans-serif">OlaXBT AI Alpha Signals Live</text>

      <!-- Bottom activity metrics -->
      <rect x="22" y="130" width="155" height="20" rx="5" fill="rgba(139,92,246,0.12)"/>
      <text x="30" y="144" fill="#d8b4fe" font-size="10" font-weight="600" font-family="monospace">MOMENTUM SCORE > 85</text>
    </g>

  </g>
</svg>`;

  console.log("Rendering SVG with Resvg...");
  const resvg = new Resvg(svg, {
    fitTo: { mode: "width", value: width },
    font: { loadSystemFonts: true, defaultFontFamily: "system-ui" },
  });

  const pngData = resvg.render();
  const pngBuffer = pngData.asPng();

  // 1. Save app/opengraph-image.png (Next.js automatically serves this at /opengraph-image.png)
  const appOgPath = path.join(process.cwd(), "app", "opengraph-image.png");
  fs.writeFileSync(appOgPath, pngBuffer);
  console.log(`Saved ${appOgPath} (${pngBuffer.length} bytes)`);

  // 2. Save public/og.png (static public asset)
  const publicOgPng = path.join(process.cwd(), "public", "og.png");
  fs.writeFileSync(publicOgPng, pngBuffer);
  console.log(`Saved ${publicOgPng} (${pngBuffer.length} bytes)`);

  // 3. Save public/og.jpg (converted via sharp for ultra-fast load fallback)
  const publicOgJpg = path.join(process.cwd(), "public", "og.jpg");
  await sharp(pngBuffer)
    .jpeg({ quality: 95, mozjpeg: true })
    .toFile(publicOgJpg);
  console.log(`Saved ${publicOgJpg}`);

  console.log("Successfully generated all OG images matching reference design!");
}

generateOgImage().catch(console.error);
