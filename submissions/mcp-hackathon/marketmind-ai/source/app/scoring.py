def calculate_score(row):
    score = 50

    if row["close"] > row["ema20"]:
        score += 10
    else:
        score -= 10

    if row["ema20"] > row["ema50"]:
        score += 10
    else:
        score -= 10

    if row["ema50"] > row["ema200"]:
        score += 10
    else:
        score -= 10

    if row["rsi14"] >= 55:
        score += 10
    elif row["rsi14"] < 45:
        score -= 10

    if row["macd"] > row["macd_signal"]:
        score += 10
    else:
        score -= 10

    score = max(0, min(100, score))

    if score >= 65:
        regime = "bullish"
    elif score <= 35:
        regime = "bearish"
    else:
        regime = "neutral"

    return {
        "score": score,
        "regime": regime
    }