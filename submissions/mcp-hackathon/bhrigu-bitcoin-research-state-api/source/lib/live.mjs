const BINANCE_TICKER = "https://data-api.binance.vision/api/v3/ticker/24hr?symbol=BTCUSDT";
const MEMPOOL_TIP = "https://mempool.space/api/blocks/tip/height";

async function timedFetch(url, fetchImpl = fetch) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 8000);
  try {
    const response = await fetchImpl(url, { signal: controller.signal, headers: { accept: "application/json,text/plain" } });
    if (!response.ok) throw new Error(`HTTP_${response.status}`);
    return response;
  } finally {
    clearTimeout(timer);
  }
}

export async function fetchMarket(fetchImpl = fetch) {
  const response = await timedFetch(BINANCE_TICKER, fetchImpl);
  const d = await response.json();
  return {
    venue: "Binance Spot",
    symbol: "BTCUSDT",
    last_price_usdt: Number(d.lastPrice),
    change_24h_pct: Number(d.priceChangePercent),
    high_24h_usdt: Number(d.highPrice),
    low_24h_usdt: Number(d.lowPrice),
    volume_24h_btc: Number(d.volume),
    source_close_time_ms: Number(d.closeTime),
    source: BINANCE_TICKER,
    security_type: "NONE"
  };
}

export async function fetchProtocol(fetchImpl = fetch) {
  try {
    const response = await timedFetch(MEMPOOL_TIP, fetchImpl);
    const height = Number(await response.text());
    if (!Number.isInteger(height) || height < 840000) throw new Error("INVALID_HEIGHT");
    return { height, source: MEMPOOL_TIP, status: "live" };
  } catch (error) {
    return { height: null, source: MEMPOOL_TIP, status: "unavailable", error: String(error.message || error) };
  }
}
