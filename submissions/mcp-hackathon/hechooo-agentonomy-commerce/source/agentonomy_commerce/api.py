"""Authenticated HTTP facade for the persistent Commerce review sandbox."""
from __future__ import annotations

import asyncio
from collections import deque
from contextlib import asynccontextmanager
from http.cookies import SimpleCookie, CookieError
import hmac
import os
from pathlib import Path
import time
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.security import HTTPBearer
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from agentonomy_commerce.settings import Settings
from agentonomy_commerce.demo_sessions import DemoError, DemoSessions, DemoRuntime
from examples.commerce.node import MarketplaceBridge, public_result


MAX_BODY_BYTES = 262144
CALL_TIMEOUT_SECONDS = 50
MODE = {"real_funds": False, "settlement_mode": "simulated", "service_transport": "http"}
IDEMPOTENCY_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$"


class ReviewHeaders:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        async def secured_send(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.extend([(b"cache-control", b"no-store"),
                                (b"x-content-type-options", b"nosniff"),
                                (b"referrer-policy", b"no-referrer"),
                                (b"x-frame-options", b"DENY")])
                if scope.get("path") == "/" or scope.get("path", "").startswith("/assets/"):
                    headers.append((b"content-security-policy", b"default-src 'self'; script-src 'self'; "
                                    b"style-src 'self'; connect-src 'self'; frame-ancestors 'none'; "
                                    b"base-uri 'none'; form-action 'none'; object-src 'none'"))
                message = {**message, "headers": headers}
            await send(message)
        await self.app(scope, receive, secured_send)


COOKIE_NAME = "agentonomy_demo"


def demo_cookie(scope):
    try:
        cookies = SimpleCookie()
        cookies.load(dict(scope.get("headers", [])).get(b"cookie", b"").decode("latin-1"))
        item = cookies.get(COOKIE_NAME)
        return item.value if item else None
    except (CookieError, ValueError):
        return None


def rate_allowed(arrivals, limit, now):
    while arrivals and arrivals[0] <= now - 60:
        arrivals.popleft()
    if len(arrivals) >= limit:
        return False
    arrivals.append(now)
    return True


class ReviewLimits:
    """Authenticate before buffering input, then bound size and request rate."""

    def __init__(self, app, *, settings, sessions):
        self.app = app
        self.settings = settings
        self.arrivals = deque()
        self.sessions = sessions
        self.bootstrap_arrivals = deque()
        self.guest_arrivals = deque()
        self.session_arrivals = {}

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "")
        is_demo = path.startswith("/demo/")
        if scope["type"] != "http" or not (path.startswith("/v1/") or is_demo):
            return await self.app(scope, receive, send)
        headers = dict(scope.get("headers", []))
        now = time.monotonic()
        if is_demo:
            if path == "/demo/session" and scope["method"] == "GET":
                return await self.app(scope, receive, send)
            if self.sessions is None:
                return await JSONResponse({"error": "demo_disabled"}, status_code=404)(scope, receive, send)
            if scope["method"] not in ("GET", "HEAD", "OPTIONS"):
                if headers.get(b"origin", b"") != self.settings.demo_origin.encode("ascii"):
                    return await JSONResponse({"error": "origin_not_allowed"}, status_code=403)(scope, receive, send)
            if path == "/demo/session":
                allowed = rate_allowed(self.bootstrap_arrivals, 20, now)
            else:
                try:
                    session = self.sessions.resolve(demo_cookie(scope))
                except DemoError as exc:
                    return await JSONResponse({"error": exc.code}, status_code=exc.status)(scope, receive, send)
                if session is None:
                    return await JSONResponse({"error": "session_required"}, status_code=401)(scope, receive, send)
                # Bounded by persisted live sessions; prune inactive rate buckets.
                self.session_arrivals = {key: value for key, value in self.session_arrivals.items()
                                         if value and value[-1] > now - 60}
                arrivals = self.session_arrivals.setdefault(session.session_id, deque())
                allowed = (rate_allowed(arrivals, self.settings.requests_per_minute, now)
                           and rate_allowed(self.guest_arrivals, self.settings.requests_per_minute * 2, now))
        else:
            supplied = headers.get(b"authorization", b"")
            expected = b"Bearer " + self.settings.api_token.encode("ascii")
            if not hmac.compare_digest(supplied, expected):
                return await JSONResponse({"error": "unauthorized"}, status_code=401,
                                          headers={"WWW-Authenticate": "Bearer"})(scope, receive, send)
            allowed = rate_allowed(self.arrivals, self.settings.requests_per_minute, now)
        if not allowed:
            return await JSONResponse({"error": "rate_limited"}, status_code=429,
                                      headers={"Retry-After": "60"})(scope, receive, send)
        body = bytearray()
        body_deadline = time.monotonic() + 10
        while True:
            try:
                message = await asyncio.wait_for(receive(), timeout=max(0, body_deadline - time.monotonic()))
            except TimeoutError:
                return await JSONResponse({"error": "request_timeout"}, status_code=408)(scope, receive, send)
            if message["type"] == "http.disconnect":
                return
            body.extend(message.get("body", b""))
            if len(body) > MAX_BODY_BYTES:
                return await JSONResponse({"error": "request_too_large"}, status_code=413)(scope, receive, send)
            if not message.get("more_body", False):
                break
        delivered = False

        async def bounded_receive():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        await self.app(scope, bounded_receive, send)


class SessionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PreviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    offering_id: str = Field(min_length=1, max_length=160)
    csv_text: str = Field(min_length=1, max_length=131072)


class ExecuteInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    preview_id: str = Field(pattern=r"^preview_[a-zA-Z0-9]+$", max_length=160)


def create_app(settings: Settings | None = None, *, bridge_factory=MarketplaceBridge):
    settings = settings or Settings.from_environment()
    sessions = DemoSessions(settings.state_dir) if settings.demo_origin else None
    demo = DemoRuntime(sessions, bridge_factory) if sessions is not None else None

    @asynccontextmanager
    async def lifespan(app):
        settings.state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        bridge = bridge_factory(settings.state_dir, worker_module="agentonomy_commerce.worker",
                                worker_args=(str(settings.merchant_port),))
        app.state.bridge = bridge
        app.state.operation_lock = asyncio.Lock()
        app.state.ready = False
        try:
            if sessions is not None:
                sessions.start()
            initial = await asyncio.to_thread(bridge.request, "snapshot")
            if "_error" in initial:
                raise RuntimeError("review worker did not initialize")
            app.state.ready = True
            yield
        finally:
            app.state.ready = False
            try:
                if demo is not None:
                    await demo.close()
            finally:
                await asyncio.to_thread(bridge.close)

    app = FastAPI(title="Agentonomy Commerce", version="0.2.0", lifespan=lifespan,
                  description="Purchase an actual CSV reconciliation report under a signed sandbox budget. "
                              "HTTP service delivery is real; settlement is simulated and no real funds are spent.")
    app.add_middleware(ReviewLimits, settings=settings, sessions=sessions)
    app.add_middleware(ReviewHeaders)
    static_dir = Path(__file__).with_name("static")
    app.mount("/assets", StaticFiles(directory=static_dir), name="assets")
    secured = [Depends(HTTPBearer(auto_error=False))]

    @app.get("/", include_in_schema=False)
    async def review_page():
        return FileResponse(static_dir / "index.html")

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request, exc):
        return JSONResponse({"error": "invalid_request", "fields": [
            {"location": list(item["loc"]), "type": item["type"]} for item in exc.errors()
        ]}, status_code=422)

    @app.exception_handler(DemoError)
    async def demo_error(_request, exc):
        return JSONResponse({"error": exc.code}, status_code=exc.status)

    @app.get("/demo/session", tags=["demo"])
    async def session_status(request: Request):
        session = sessions.resolve(demo_cookie(request.scope)) if sessions is not None else None
        return {"enabled": sessions is not None, "authenticated": session is not None,
                **({"session_id": session.session_id, "expires_at": session.expires_at} if session else {})}

    @app.post("/demo/session", tags=["demo"])
    async def start_session(request: Request, body: SessionInput):
        if demo is None:
            raise HTTPException(404, detail="demo_disabled")
        session, token = await demo.start_session(demo_cookie(request.scope))
        response = JSONResponse({"enabled": True, "authenticated": True,
                                 "session_id": session.session_id, "expires_at": session.expires_at})
        if token is not None:
            response.set_cookie(COOKIE_NAME, token, max_age=max(0, session.expires_at - int(time.time())),
                                httponly=True, secure=settings.demo_origin.startswith("https://"),
                                samesite="strict", path="/")
        return response

    async def call(method, arguments=None, *, request):
        if request.url.path.startswith("/demo/"):
            if demo is None:
                raise HTTPException(404, detail="demo_disabled")
            result = await demo.call(demo_cookie(request.scope), method, arguments)
            return checked_result(result)
        return await private_call(method, arguments)

    async def private_call(method, arguments=None):
        if not app.state.ready:
            raise HTTPException(503, detail="worker_unavailable")
        try:
            await asyncio.wait_for(app.state.operation_lock.acquire(), timeout=2)
        except TimeoutError as exc:
            raise HTTPException(429, detail="operation_in_progress; read the existing purchase") from exc
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(app.state.bridge.request, method, arguments), timeout=CALL_TIMEOUT_SECONDS)
        except (RuntimeError, OSError, ValueError) as exc:
            app.state.ready = False
            process = getattr(app.state.bridge, "process", None)
            if process is not None and process.poll() is None:
                process.terminate()
            await asyncio.to_thread(app.state.bridge.close)
            raise HTTPException(503, detail="worker_unavailable; inspect the existing purchase before retrying") from exc
        finally:
            app.state.operation_lock.release()
        return checked_result(result)

    def checked_result(result):
        if "_error" in result:
            code = result["_error"]
            status = {"not_found": 404, "invalid_input": 422, "idempotency_conflict": 409}.get(code, 503)
            raise HTTPException(status, detail=code)
        return result

    @app.get("/health", tags=["verification"])
    async def health():
        ready = getattr(app.state, "ready", False)
        bridge = getattr(app.state, "bridge", None)
        process = getattr(bridge, "process", None)
        if getattr(bridge, "broken", False) or (process is not None and process.poll() is not None):
            ready = False
            app.state.ready = False
        return JSONResponse({"status": "ok" if ready else "unavailable", "commit": settings.source_commit,
                             **MODE}, status_code=200 if ready else 503)

    @app.get("/.well-known/xagent-verification.json", tags=["verification"])
    async def proof():
        return {"schemaVersion": 1, "slug": settings.project_slug, "commit": settings.source_commit}

    @app.get("/demo/v1/services", tags=["demo"])
    @app.get("/v1/services", dependencies=secured, tags=["commerce"])
    async def services(request: Request):
        return {**await call("search", request=request), **MODE}

    @app.get("/demo/v1/budget", tags=["demo"])
    @app.get("/v1/budget", dependencies=secured, tags=["commerce"])
    async def budget(request: Request):
        return {**await call("snapshot", request=request), **MODE}

    @app.post("/demo/v1/previews", tags=["demo"])
    @app.post("/v1/previews", dependencies=secured, tags=["commerce"],
              description="Freeze CSV input and price. Reusing the same Idempotency-Key preserves the preview; "
                          "changing its input returns 409. Preview expires after 300 seconds. Does not charge.")
    async def preview(request: Request, body: PreviewInput, idempotency_key: Annotated[str, Header(pattern=IDEMPOTENCY_PATTERN)]):
        result = await call("preview", {**body.model_dump(), "idempotency_key": idempotency_key}, request=request)
        return {**public_result("create_clink_purchase_preview", result), **MODE}

    @app.post("/demo/v1/purchases", tags=["demo"])
    @app.post("/v1/purchases", dependencies=secured, tags=["commerce"],
              description="Consumes 0.30 sandbox USDC from the existing signed budget and calls the HTTP merchant. "
                          "Replay the same preview; never create a new purchase to recover an uncertain outcome.")
    async def execute(request: Request, body: ExecuteInput):
        result = await call("execute", body.model_dump(), request=request)
        return {**public_result("execute_clink_purchase", result), **MODE}

    @app.get("/demo/v1/purchases/{purchase_id}", tags=["demo"])
    @app.get("/v1/purchases/{purchase_id}", dependencies=secured, tags=["commerce"],
             description="Read persisted order and retained result without charging; results expire after 7 days.")
    async def purchase(request: Request, purchase_id: str):
        if len(purchase_id) > 160:
            raise HTTPException(404, detail="not_found")
        result = await call("purchase", {"purchase_id": purchase_id}, request=request)
        return {**public_result("get_clink_purchase", result), **MODE}

    return app


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(create_app(), host=os.environ.get("AGENTONOMY_HOST", "127.0.0.1"),
                port=int(os.environ.get("AGENTONOMY_PORT", "8080")))
