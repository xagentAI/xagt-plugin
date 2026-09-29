from __future__ import annotations
import secrets
from fastapi.responses import JSONResponse

def require_internal_token(config):
    async def guard(request,call_next):
        if request.url.path=="/healthz": return await call_next(request)
        expected=config.clink_internal_api_token
        if not expected: return JSONResponse(status_code=503,content={"detail":"CLINK_CORE_INTERNAL_API_TOKEN is required"})
        supplied=request.headers.get("authorization","").removeprefix("Bearer ")
        if not secrets.compare_digest(supplied,expected): return JSONResponse(status_code=401,content={"detail":"invalid internal bearer token"})
        return await call_next(request)
    return guard
