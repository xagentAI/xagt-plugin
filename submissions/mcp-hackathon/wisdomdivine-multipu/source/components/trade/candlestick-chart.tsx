"use client";

interface CandlestickChartProps {
  currentPrice: number;
  priceDirection?: "up" | "down" | "flat";
  gasSymbol: string;
  pairAddress?: string | null;
  chainId?: string | null;
  tokenSymbol?: string;
}

function formatPrice(val: number): string {
  if (val <= 0) return "$0.00";
  if (val < 0.00001) return `$${val.toFixed(8)}`;
  if (val < 0.01) return `$${val.toFixed(6)}`;
  if (val < 1) return `$${val.toFixed(4)}`;
  return `$${val.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 4 })}`;
}

export function CandlestickChart({
  currentPrice,
  gasSymbol,
  pairAddress,
  chainId,
  tokenSymbol,
}: CandlestickChartProps) {
  const normalizedChain = chainId ? chainId.toLowerCase() : "solana";
  const dexScreenerUrl = pairAddress
    ? `https://dexscreener.com/${normalizedChain}/${pairAddress}`
    : null;

  if (pairAddress) {
    return (
      <div className="bg-[#181818] p-4 rounded-2xl flex flex-col gap-3">
        {/* Header Toolbar */}
        <div className="flex items-center justify-between px-1 flex-wrap gap-2">
          <div className="flex items-center gap-2.5">
            <span className="text-xs font-mono font-medium text-white">
              Live DEX Chart
            </span>
            {tokenSymbol && (
              <span className="text-[11px] font-mono text-neutral-400">
                ${tokenSymbol}
              </span>
            )}
            <span className="text-[10px] font-mono uppercase px-2 py-0.5 rounded bg-white/[0.04] text-neutral-400">
              {normalizedChain}
            </span>
          </div>

          <div className="flex items-center gap-3">
            {currentPrice > 0 && (
              <div className="text-xs font-mono text-neutral-300">
                {formatPrice(currentPrice)}
              </div>
            )}
            {dexScreenerUrl && (
              <a
                href={dexScreenerUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="text-[11px] font-mono text-neutral-400 hover:text-white transition-colors"
              >
                DexScreener
              </a>
            )}
          </div>
        </div>

        {/* Live DEX Chart */}
        <div className="w-full h-[520px] rounded-xl overflow-hidden bg-[#121212]">
          <iframe
            src={`https://dexscreener.com/${normalizedChain}/${pairAddress}?embed=1&theme=dark&trades=0&info=0`}
            title="Live DEX Chart"
            className="w-full h-full border-0"
            allow="clipboard-write"
          />
        </div>
      </div>
    );
  }

  return (
    <div className="bg-[#181818] p-8 rounded-2xl flex flex-col items-center justify-center min-h-[380px] gap-3 text-center">
      <span className="text-sm font-sans font-medium text-white">
        DEX Chart
      </span>
      <p className="text-xs font-mono text-neutral-400 max-w-md leading-relaxed">
        Liquidity pool pending automated market maker indexing. Chart will stream live automatically once liquidity pool transactions are indexed.
      </p>
      {currentPrice > 0 && (
        <div className="text-xs font-mono text-neutral-300 mt-2 px-3 py-1 rounded bg-white/[0.04]">
          Initial Reference: {formatPrice(currentPrice)} {gasSymbol}
        </div>
      )}
    </div>
  );
}
