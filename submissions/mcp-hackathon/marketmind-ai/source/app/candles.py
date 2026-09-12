import requests
import pandas as pd

KRAKEN_URL = "https://api.kraken.com/0/public/OHLC"


def get_candles(symbol: str, interval: str = "1h", limit: int = 250):
    symbol = symbol.upper()

    if not symbol.endswith("USDT"):
        raise ValueError("Only USDT pairs are supported")

    base = symbol[:-4]

    # Kraken uses XBT instead of BTC
    if base == "BTC":
        pair = "XBTUSD"
    else:
        pair = f"{base}USD"

    response = requests.get(
        KRAKEN_URL,
        params={
            "pair": pair,
            "interval": 60
        },
        timeout=15
    )

    response.raise_for_status()

    result = response.json()

    if result.get("error"):
        raise RuntimeError(
            "Kraken market data error: " + str(result["error"])
        )

    data = result["result"]

    pair_key = [key for key in data.keys() if key != "last"][0]
    candles = data[pair_key]

    if not candles:
        raise RuntimeError("No candle data returned")

    df = pd.DataFrame(
        candles,
        columns=[
            "open_time",
            "open",
            "high",
            "low",
            "close",
            "vwap",
            "volume",
            "count"
        ]
    )

    df["open_time"] = pd.to_datetime(
        df["open_time"],
        unit="s"
    )

    for column in ["open", "high", "low", "close", "volume"]:
        df[column] = pd.to_numeric(
            df[column],
            errors="coerce"
        )

    df = df[
        [
            "open_time",
            "open",
            "high",
            "low",
            "close",
            "volume"
        ]
    ]

    df = df.dropna()
    df = df.tail(limit).reset_index(drop=True)

    return df