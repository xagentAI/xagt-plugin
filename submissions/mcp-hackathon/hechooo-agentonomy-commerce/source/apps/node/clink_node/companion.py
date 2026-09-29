from __future__ import annotations

from pathlib import Path
from urllib.parse import unquote

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles


STATIC_DIR = Path(__file__).with_name("static")
MINIAPP_SECURITY_HEADERS = {
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "Content-Security-Policy": (
        "default-src 'self'; "
        "script-src 'self' https://telegram.org; "
        "connect-src 'self'; "
        "style-src 'self'; "
        "img-src 'self' data:; "
        "object-src 'none'; "
        "base-uri 'none'; "
        "form-action 'self'"
    ),
}
_MINIAPP_STATIC_ASSETS = frozenset(
    {"miniapp.html", "miniapp.css", "miniapp.js"}
)


class _CompanionStaticFiles(StaticFiles):
    def __init__(self, *, miniapp_enabled: bool) -> None:
        super().__init__(directory=STATIC_DIR)
        self._miniapp_enabled = miniapp_enabled

    async def get_response(self, path: str, scope: dict) -> Response:
        if not self._miniapp_enabled and _targets_miniapp_asset(path):
            return Response(status_code=404)
        return await super().get_response(path, scope)


def attach_companion(
    app: FastAPI,
    *,
    miniapp_enabled: bool = False,
) -> None:
    app.mount(
        "/static",
        _CompanionStaticFiles(miniapp_enabled=miniapp_enabled),
        name="static",
    )

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def companion_home() -> str:
        return (STATIC_DIR / "index.html").read_text(encoding="utf-8")

    @app.get(
        "/console",
        response_class=HTMLResponse,
        include_in_schema=False,
    )
    @app.get(
        "/console/",
        response_class=HTMLResponse,
        include_in_schema=False,
    )
    def companion_console() -> HTMLResponse:
        return HTMLResponse(
            (STATIC_DIR / "console.html").read_text(encoding="utf-8"),
            headers=MINIAPP_SECURITY_HEADERS,
        )

    if miniapp_enabled:

        @app.get(
            "/miniapp/",
            response_class=HTMLResponse,
            include_in_schema=False,
        )
        def miniapp_home() -> HTMLResponse:
            return HTMLResponse(
                (STATIC_DIR / "miniapp.html").read_text(encoding="utf-8"),
                headers=MINIAPP_SECURITY_HEADERS,
            )

    @app.get(
        "/interactions/{interaction_id}",
        response_class=HTMLResponse,
        include_in_schema=False,
    )
    def interaction(interaction_id: str) -> str:
        template = (STATIC_DIR / "interaction.html").read_text(
            encoding="utf-8"
        )
        safe_id = (
            interaction_id
            if interaction_id.replace("_", "").isalnum()
            else "invalid"
        )
        return template.replace("{{INTERACTION_ID}}", safe_id)


def _targets_miniapp_asset(path: str) -> bool:
    candidate = path.replace("\\", "/")
    for _ in range(3):
        decoded = unquote(candidate)
        if decoded == candidate:
            break
        candidate = decoded.replace("\\", "/")
    return any(
        part in _MINIAPP_STATIC_ASSETS
        for part in candidate.split("/")
    )
