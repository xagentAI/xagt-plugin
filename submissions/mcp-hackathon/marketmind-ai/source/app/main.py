import os

from fastapi import FastAPI

from candles import get_candles
from indicators import calculate_indicators
from scoring import calculate_score


app = FastAPI(
    title="MarketMind AI",
    description="Agent-callable crypto market intelligence API",
    version="0.3.0"
)


PROJECT_SLUG = "marketmind-ai"


@app.get("/")
def root():
    return {
        "name": "MarketMind AI",
        "status": "online",
        "version": "0.3.0"
    }


@app.get("/health")
def health():
    commit = os.getenv("RENDER_GIT_COMMIT", "development")

    return {
        "status": "ok",
        "commit": commit
    }


@app.get("/.well-known/xagent-verification.json")
def xagent_verification():
    commit = os.getenv("RENDER_GIT_COMMIT", "development")

    return {
        "schemaVersion": 1,
        "slug": PROJECT_SLUG,
        "commit": commit
    }


@app.get("/v1/market-intelligence/{symbol}")
def market_intelligence(symbol: str):
    df = get_candles(symbol)

    df = calculate_indicators(df)

    latest = df.iloc[-1]

    score = calculate_score(latest)

    return {
        "symbol": symbol.upper(),
        "price": float(latest["close"]),
        "indicators": {
            "ema20": float(latest["ema20"]),
            "ema50": float(latest["ema50"]),
            "ema200": float(latest["ema200"]),
            "rsi14": float(latest["rsi14"]),
            "macd": float(latest["macd"]),
            "macdSignal": float(latest["macd_signal"])
        },
        "marketAssessment": score
    }