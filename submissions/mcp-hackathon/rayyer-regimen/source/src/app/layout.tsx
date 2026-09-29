import type { Metadata, Viewport } from 'next';
import type { ReactNode } from 'react';
import './globals.css';

export const metadata: Metadata = {
  title: 'Regimen',
  description:
    'Statistical validation desk for OlaXBT Nexus trading strategies: is the track record distinguishable from luck, and in which market regimes does it hold?',
};

export const viewport: Viewport = {
  colorScheme: 'dark',
  themeColor: '#05070a',
};

/**
 * The typefaces are loaded as Google-hosted stylesheets rather than bundled, which keeps
 * the build independent of a font registry at compile time.
 *
 * Bricolage Grotesque carries the display voice (irregular, made rather than committee-
 * drawn); Schibsted Grotesk is the newspaper grotesque for reading; DM Mono is the
 * telemetry face and is used for numbers and readouts and for nothing else. The brief
 * names Commit Mono for telemetry — it is not on Google Fonts, so DM Mono stands in with
 * the same job description until it can be self-hosted.
 */
const FONT_HREF =
  'https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wdth,wght@10..48,75..100,200..800&family=DM+Mono:ital,wght@0,300;0,400;0,500;1,400&family=Schibsted+Grotesk:ital,wght@0,400..800;1,400..700&display=swap';

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="" />
        <link rel="stylesheet" href={FONT_HREF} />
      </head>
      <body>{children}</body>
    </html>
  );
}
