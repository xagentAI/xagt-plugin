import requests

BINANCE_URL = "https://fapi.binance.com/fapi/v1/ticker/24hr"


def get_market_data(symbol: str):
    symbol = symbol.upper()

    response = requests.get(
        BINANCE_URL,
        params={"symbol": symbol},
        timeout=10
    )

    response.raise_for_status()
    data = response.json()

    return {
        "symbol": data["symbol"],
        "price": float(data["lastPrice"]),
        "priceChange24h": float(data["priceChangePercent"]),
        "volume24h": float(data["volume"]),
        "quoteVolume24h": float(data["quoteVolume"]),
        "high24h": float(data["highPrice"]),
        "low24h": float(data["lowPrice"])
    }