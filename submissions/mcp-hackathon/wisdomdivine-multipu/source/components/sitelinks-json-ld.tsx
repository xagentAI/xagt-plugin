export function SitelinksJsonLd() {
  const jsonLd = {
    "@context": "https://schema.org",
    "@graph": [
      {
        "@type": "WebSite",
        "@id": "https://multipu.fun/#website",
        "url": "https://multipu.fun",
        "name": "Multipu",
        "description":
          "Multi-chain token launch orchestrator, real-time DEX terminal, and autonomous AI trading protocol for Solana, BNB Chain, and Robinhood Chain.",
        "publisher": {
          "@id": "https://multipu.fun/#organization",
        },
        "potentialAction": {
          "@type": "SearchAction",
          "target": {
            "@type": "EntryPoint",
            "urlTemplate": "https://multipu.fun/dashboard/explore?search={search_term_string}",
          },
          "query-input": "required name=search_term_string",
        },
      },
      {
        "@type": "Organization",
        "@id": "https://multipu.fun/#organization",
        "name": "Multipu",
        "url": "https://multipu.fun",
        "logo": {
          "@type": "ImageObject",
          "url": "https://multipu.fun/logo.png",
          "width": 512,
          "height": 512,
        },
      },
      {
        "@type": "SoftwareApplication",
        "@id": "https://multipu.fun/#application",
        "name": "Multipu Platform",
        "applicationCategory": "DeFiApplication",
        "operatingSystem": "Web",
        "url": "https://multipu.fun",
        "offers": {
          "@type": "Offer",
          "price": "0",
          "priceCurrency": "USD",
        },
        "featureList": [
          "Multi-chain token deployer (Solana, BNB Chain, Robinhood Chain)",
          "Simultaneous dispatch to Pump.fun, Meteora, Bags, Four.meme, and Pons",
          "Real-time DEX trading terminal with live candlestick charting",
          "Autonomous KeeperHub MCP and OlaXBT AI agent execution protocol",
          "Non-custodial Solana and EVM Web3 wallet authentication",
        ],
      },
      {
        "@type": "ItemList",
        "@id": "https://multipu.fun/#sitelinks",
        "name": "Multipu Primary Sitelinks",
        "itemListElement": [
          {
            "@type": "SiteNavigationElement",
            "position": 1,
            "name": "Token Launchpad Orchestrator",
            "description": "Deploy and launch tokens simultaneously across Solana, BNB Chain, and Robinhood Chain.",
            "url": "https://multipu.fun/launch",
          },
          {
            "@type": "SiteNavigationElement",
            "position": 2,
            "name": "Meme Token Explorer",
            "description": "Live bonding curve scanner and real-time market tracker across multi-chain launchpads.",
            "url": "https://multipu.fun/dashboard/explore",
          },
          {
            "@type": "SiteNavigationElement",
            "position": 3,
            "name": "DEX Trading Terminal",
            "description": "Instant non-custodial swaps with real-time price feeds, depth, and momentum analytics.",
            "url": "https://multipu.fun/dashboard/trade",
          },
          {
            "@type": "SiteNavigationElement",
            "position": 4,
            "name": "Token Manager & Registry",
            "description": "Monitor active deployments, draft tokens, and multi-chain mint addresses.",
            "url": "https://multipu.fun/dashboard/tokens",
          },
          {
            "@type": "SiteNavigationElement",
            "position": 5,
            "name": "Launchpad Deployments",
            "description": "Track live launchpad dispatches across Pump.fun, Meteora, Bags, Four.meme, and Pons.",
            "url": "https://multipu.fun/dashboard/launches",
          },
          {
            "@type": "SiteNavigationElement",
            "position": 6,
            "name": "Developer API & MCP Agent Tooling",
            "description": "Programmatic REST API keys, webhooks, and Model Context Protocol server endpoints for AI agents.",
            "url": "https://multipu.fun/dashboard/api",
          },
          {
            "@type": "SiteNavigationElement",
            "position": 7,
            "name": "Developer Documentation & MCP Protocol",
            "description": "Comprehensive REST API guides, KeeperHub MCP schemas, and multi-chain integration docs.",
            "url": "https://docs.multipu.fun",
          },
          {
            "@type": "SiteNavigationElement",
            "position": 8,
            "name": "Multi-Chain Portfolio Dashboard",
            "description": "Unified dashboard for Solana SOL, BNB, and Robinhood Chain ETH balances.",
            "url": "https://multipu.fun/dashboard",
          },
          {
            "@type": "SiteNavigationElement",
            "position": 9,
            "name": "Creator Fee Earnings",
            "description": "Track creator royalties, launchpad fee accruals, and revenue analytics.",
            "url": "https://multipu.fun/dashboard/earnings",
          },
        ],
      },
    ],
  };

  return (
    <script
      type="application/ld+json"
      dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }}
    />
  );
}
