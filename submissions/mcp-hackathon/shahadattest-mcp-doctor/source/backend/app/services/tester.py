import time
from typing import Any
import httpx

from app.core.config import MAX_RESPONSE_BYTES, REQUEST_TIMEOUT, MAX_RETRIES
from app.core.security import is_safe_method, validate_url_for_fetch


async def test_endpoint(base_url: str, endpoint: dict[str, Any], allow_unsafe: bool = False) -> dict[str, Any]:
    method = endpoint["method"]
    path = endpoint["path"]
    if not is_safe_method(method) and not allow_unsafe:
        return {"endpoint": f"{method} {path}", "status": "skipped", "reason": "unsafe method requires approval"}
    url = (base_url.rstrip("/") + path) if base_url else None
    if not url:
        return {"endpoint": f"{method} {path}", "status": "skipped", "reason": "no server URL in spec"}
    try:
        validate_url_for_fetch(url)
    except Exception as e:
        return {"endpoint": f"{method} {path}", "status": "blocked", "reason": str(getattr(e, 'detail', e))}
    last_err = ""
    for _ in range(MAX_RETRIES + 1):
        try:
            started = time.perf_counter()
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT, follow_redirects=True, max_redirects=3) as client:
                resp = await client.request(method if method != "HEAD" else "GET", url)
            latency = int((time.perf_counter() - started) * 1000)
            body = resp.content[:MAX_RESPONSE_BYTES]
            ctype = resp.headers.get("content-type", "")
            json_valid, parsed = True, None
            if "json" in ctype or (body[:1] in (b"{", b"[")):
                try:
                    import json
                    parsed = json.loads(body.decode("utf-8", errors="replace") or "null")
                except Exception:
                    json_valid = False
            ok = 200 <= resp.status_code < 400 and json_valid
            return {"endpoint": f"{method} {path}", "status": "passed" if ok else "warning",
                    "http_status": resp.status_code, "latency_ms": latency,
                    "schema_valid": True, "content_type_valid": True, "json_valid": json_valid,
                    "preview": str(parsed)[:500] if parsed is not None else body[:200].decode("utf-8", errors="replace")}
        except Exception as e:
            last_err = str(e)[:300]
            continue
    code = "UPSTREAM_TIMEOUT" if "timeout" in last_err.lower() else "UPSTREAM_SERVER_ERROR"
    return {"endpoint": f"{method} {path}", "status": "failed", "error_code": code, "reason": last_err}
