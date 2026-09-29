import asyncio

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from clink_node.agent_access_http import ControlIngressMiddleware


CATALOG_PATH = "/v1/marketplace/services"
CONTROL_TOKEN = "control-token-for-homepage-tests"


def _app() -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.get(CATALOG_PATH)
    async def catalog(request: Request):
        return {"route": request.url.path, "query": request.url.query}

    @app.get("/v1/c/sentinel")
    async def control_sentinel():
        return {"route": "control"}

    @app.get("/account")
    async def account():
        return JSONResponse(
            {"route": "account"},
            headers={"Cache-Control": "public, max-age=60"},
        )

    @app.post("/v1/opc/pairings")
    async def opc_pairing():
        return {"route": "opc"}

    @app.get("/v1/node")
    async def legacy_node():
        return {"route": "legacy"}

    app.add_middleware(
        ControlIngressMiddleware,
        control_token=CONTROL_TOKEN,
    )
    return app


def test_public_catalogue_get_is_admitted_and_dispatched_to_the_route():
    async def scenario():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=_app()),
            base_url="http://testserver",
        ) as client:
            response = await client.get(CATALOG_PATH, params={"limit": 7})

        assert response.status_code == 200
        assert response.json() == {
            "route": CATALOG_PATH,
            "query": "limit=7",
        }

    asyncio.run(scenario())


def test_public_catalogue_admission_is_exact_for_methods_and_paths():
    async def scenario():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=_app()),
            base_url="http://testserver",
        ) as client:
            for method in ("POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"):
                response = await client.request(method, CATALOG_PATH)
                assert response.status_code == 404, (method, response.text)

            for path in (
                CATALOG_PATH + "/",
                "/v1/marketplace/unknown",
            ):
                response = await client.get(path)
                assert response.status_code == 404, (path, response.text)

    asyncio.run(scenario())


def test_sensitive_legacy_and_control_ingress_boundaries_remain_unchanged():
    async def scenario():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=_app()),
            base_url="http://testserver",
        ) as client:
            for path in (
                "/v1/node",
                "/v1/modules",
                "/v1/capabilities",
                "/v1/account/readiness",
                "/v1/account/summary",
                "/v1/activity",
                "/openapi.json",
            ):
                response = await client.get(path)
                assert response.status_code == 404, (path, response.text)

            assert (await client.get("/v1/c/sentinel")).status_code == 401
            assert (
                await client.get(
                    "/v1/c/sentinel",
                    headers={"Authorization": "Bearer wrong-control-token"},
                )
            ).status_code == 401
            assert (
                await client.get(
                    "/v1/c/sentinel",
                    headers={"Authorization": f"Bearer {CONTROL_TOKEN}"},
                )
            ).status_code == 200

            assert (await client.get("/v1/opc/pairings")).status_code == 404
            assert (
                await client.post("/v1/opc/unknown")
            ).status_code == 404

            account = await client.get("/account")
            assert account.status_code == 200
            assert account.headers["cache-control"] == "no-store"

    asyncio.run(scenario())
