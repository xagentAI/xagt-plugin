import asyncio
import random
from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse, PlainTextResponse

app = FastAPI(title="Broken Demo API", version="0.1.0",
              servers=[{"url": "http://localhost:3220"}])


async def chaos(mode: str | None):
    if mode == "timeout":
        await asyncio.sleep(12)
    elif mode == "slow":
        await asyncio.sleep(3)
    elif mode == "500":
        return JSONResponse({"error": "boom"}, status_code=500)
    elif mode == "malformed":
        return PlainTextResponse("{not-json", status_code=200)
    elif mode == "missing_field":
        return JSONResponse({})
    elif mode == "429":
        return JSONResponse({"error": "rate limited"}, status_code=429)
    return None


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/weather", operation_id="getWeather")
async def weather(mode: str | None = Query(default=None)):
    hit = await chaos(mode)
    if hit is not None:
        return hit
    # intentionally inconsistent schema
    if random.random() < 0.5:
        return {"tmp": "31 C", "desc": "sun"}
    return {"temperature": 31, "weather": "sunny"}


@app.get("/product", operation_id="getProduct")
async def product(mode: str | None = Query(default=None)):
    hit = await chaos(mode)
    if hit is not None:
        return hit
    if random.random() < 0.5:
        return {"price": "149.99", "name": "Lamp"}
    return {"price": 149.99, "name": "Lamp"}


@app.get("/user", operation_id="getUser")
async def user(mode: str | None = Query(default=None)):
    hit = await chaos(mode)
    if hit is not None:
        return hit
    return {"id": 1, "name": None, "email": "a@example.com"}


@app.get("/exchange-rate", operation_id="getRate")
async def rate(mode: str | None = Query(default=None)):
    hit = await chaos(mode)
    if hit is not None:
        return hit
    await asyncio.sleep(1.5)
    return {"pair": "USD-BDT", "rate": "117.5"}
