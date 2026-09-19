from __future__ import annotations

from itertools import count

from fastapi import APIRouter, Query, Request, Response

router = APIRouter(prefix="/demo")
_weather_calls = count()
_product_calls = count()
_catalog = [
    {"id": "p1", "name": "Lamp", "price": 149.99},
    {"id": "p2", "name": "Desk", "price": 329.0},
    {"id": "p3", "name": "Chair", "price": 219.5},
    {"id": "p4", "name": "Shelf", "price": 89.0},
    {"id": "p5", "name": "Clock", "price": 45.0},
    {"id": "p6", "name": "Rug", "price": 175.0},
    {"id": "p7", "name": "Vase", "price": 59.0},
]


@router.get("/openapi.json", include_in_schema=False)
async def demo_openapi(request: Request):
    base = str(request.base_url).rstrip("/") + "/demo"
    return {
        "openapi": "3.0.3",
        "info": {"title": "Deliberately Inconsistent Shop API", "version": "0.1.0"},
        "servers": [{"url": base}],
        "paths": {
            "/weather": {"get": {"summary": "Weather", "parameters": [{"name": "q", "in": "query"}], "responses": {"200": {"description": "ok"}}}},
            "/product": {"get": {"operationId": "getProduct", "responses": {"200": {"description": "ok"}}}},
            "/user": {"get": {"operationId": "getUser", "summary": "Get user profile", "responses": {"200": {"description": "ok"}}}},
            "/items": {
                "get": {
                    "operationId": "listItems",
                    "summary": "List the stable demo catalog",
                    "parameters": [
                        {"name": "cursor", "in": "query", "schema": {"type": "string"}},
                        {"name": "limit", "in": "query", "schema": {"type": "integer", "minimum": 1, "maximum": 3, "default": 3}},
                    ],
                    "responses": {
                        "200": {
                            "description": "A snapshot-consistent catalog page",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "required": ["items", "has_more", "next_cursor", "total", "snapshot_id"],
                                        "properties": {
                                            "items": {"type": "array", "items": {"type": "object", "required": ["id", "name", "price"], "properties": {"id": {"type": "string"}, "name": {"type": "string"}, "price": {"type": "number"}}}},
                                            "has_more": {"type": "boolean"},
                                            "next_cursor": {"type": ["string", "null"]},
                                            "total": {"type": "integer"},
                                            "snapshot_id": {"type": "string"},
                                        },
                                    }
                                }
                            },
                        }
                    },
                }
            },
        },
    }


@router.get("/weather", include_in_schema=False)
async def weather():
    if next(_weather_calls) % 2:
        return {"temperature": 31, "weather": "sunny"}
    return {"tmp": "31 C", "desc": "sun"}


@router.get("/product", include_in_schema=False)
async def product():
    price = 149.99 if next(_product_calls) % 2 else "149.99"
    return {"name": "Lamp", "price": price}


@router.get("/user", include_in_schema=False)
async def user():
    return {"id": 1, "name": None, "email": "demo@example.com"}


@router.get("/items", include_in_schema=False)
async def items(cursor: str | None = None, limit: int = Query(default=3, ge=1, le=3)):
    try:
        start = int(cursor) if cursor is not None else 0
    except ValueError:
        start = len(_catalog)
    page = _catalog[start : start + limit]
    next_offset = start + len(page)
    has_more = next_offset < len(_catalog)
    return {
        "items": page,
        "has_more": has_more,
        "next_cursor": str(next_offset) if has_more else None,
        "total": len(_catalog),
        "snapshot_id": "demo-catalog-v1",
    }


@router.get("/providers/atlas", include_in_schema=False)
async def atlas_provider():
    return {"provider": "atlas", "quote": {"amount_usd": 18.40, "eta_minutes": 38}, "observed_at": "live"}


@router.get("/providers/beacon", include_in_schema=False)
async def beacon_provider():
    return {"provider": "beacon", "quote": {"amount_usd": 18.44, "eta_minutes": 35}, "observed_at": "live"}


@router.get("/providers/legacy", include_in_schema=False)
async def legacy_provider():
    return {"provider": "legacy", "quote": {"amount_usd": "call us", "eta_minutes": None}, "observed_at": "live"}


@router.get("/providers/offline", include_in_schema=False)
async def offline_provider():
    return Response(content='{"error":"temporarily unavailable"}', status_code=503, media_type="application/json")
