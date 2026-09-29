import { MinimalNav } from "@/components/landing/minimal-nav";
import { HeroStatus } from "@/components/landing/hero-status";
import { BauhausShowcase } from "@/components/landing/bauhaus-showcase";
import { ProductList } from "@/components/landing/product-list";
import { KeyboardTerminal } from "@/components/landing/keyboard-terminal";
import { MonomodFooter } from "@/components/landing/monomod-footer";

export default function Home() {
  return (
    <div className="min-h-screen bg-black text-white selection:bg-accent selection:text-white">
      {/* Top Minimalist Navigation with Multipu Logo */}
      <MinimalNav />

      <main className="flex-1">
        {/* Hero: Editorial typography, custom cursor SVG, proof stats & squiggle */}
        <HeroStatus />

        {/* Dark canvas, Bauhaus abstract vector composition & 2x2 colored tile grid */}
        <BauhausShowcase />

        {/* Lilac launchpad list with ▶▶ markers, metrics, and Ready-to-launch banner */}
        <ProductList />

        {/* Technical mechanical keyboard wireframe vector illustration */}
        <KeyboardTerminal />
      </main>

      {/* Footer: Monomod-style footer CTA banner, Multipu logo, 4-column directory, and copyright bar */}
      <MonomodFooter />
    </div>
  );
}
