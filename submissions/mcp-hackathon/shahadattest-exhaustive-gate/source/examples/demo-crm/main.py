"""Deterministic demo CRM: 347 invoices, 52 products, chaos modes."""
import asyncio
from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse

app = FastAPI(title="Demo CRM", version="0.1.0")

INVOICES = [{"id": f"inv_{i:04d}", "status": "unpaid" if i % 3 else "paid",
             "amount": 50 + (i * 37) % 900} for i in range(1, 521)]  # 520 total, 347 unpaid
UNPAID = [inv for inv in INVOICES if inv["status"] == "unpaid"]  # exactly 347
PRODUCTS = [{"id": f"prod_{i:03d}", "price": 5 + (i * 13) % 200} for i in range(1, 53)]
PRODUCTS[7]["price"] = 3  # cheapest: prod_008
CUSTOMERS = [{"id": f"cust_{i:03d}", "active": bool(i % 2)} for i in range(1, 61)]

PAGE = 100
PRODUCT_PAGE = 20


def paginate(rows: list, cursor: str | None):
    start = int(cursor.split("_")[1]) if cursor and cursor.startswith("pg_") else 0
    chunk = rows[start:start + PAGE]
    nxt = start + PAGE
    out = f"pg_{nxt}" if nxt < len(rows) else None
    return chunk, out, nxt < len(rows)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/invoices")
async def invoices(cursor: str | None = None, status: str | None = Query(default=None),
                   mode: str = "normal"):
    rows = [r for r in UNPAID if status is None or r["status"] == status]
    pg = (int(cursor.split("_")[1]) // PAGE + 1) if cursor and cursor.startswith("pg_") else 1
    if mode == "timeout_page_3" and pg == 3:
        await asyncio.sleep(12)
    if mode == "rate_limit_page_2" and pg == 2:
        return JSONResponse({"error": "rate limited"}, status_code=429)
    snap = "snapshot_A"
    if mode == "snapshot_change" and pg >= 3:
        snap = "snapshot_B"
    chunk, out, more = paginate(rows, cursor)
    if mode == "broken_cursor" and pg == 2:
        out = "pg_WRONG"
    if mode == "duplicate_page":
        out = cursor  # loop: cursor never advances
        more = True
    total = len(rows) + (5 if mode == "wrong_total" else 0)
    return {"records": chunk, "cursor_out": out, "has_more": more,
            "snapshot_id": snap, "authoritative_total": total, "page": pg}


@app.get("/products")
async def products(cursor: str | None = None, mode: str = "normal"):
    start = int(cursor.split("_")[1]) if cursor and cursor.startswith("pg_") else 0
    chunk = PRODUCTS[start:start + PRODUCT_PAGE]
    nxt = start + PRODUCT_PAGE
    out = f"pg_{nxt}" if nxt < len(PRODUCTS) else None
    return {"records": chunk, "cursor_out": out, "has_more": nxt < len(PRODUCTS),
            "snapshot_id": "snapshot_A", "page": start // PRODUCT_PAGE + 1}


@app.get("/customers")
async def customers(cursor: str | None = None):
    chunk, out, more = paginate(CUSTOMERS, cursor)
    return {"records": chunk, "cursor_out": out, "has_more": more, "snapshot_id": "snapshot_A"}
