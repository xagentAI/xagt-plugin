"""
app.py · MCPForge deployment entrypoint (single-port HTTP service)

Cloud platforms (and the publish capability in this workspace) inject a PORT environment variable and expect 0.0.0.0,
so this module provides the standard entrypoint, sharing one FastAPI app with demo_app.py:

    /            four-stage walkthrough page
    /api/health  health check (live evidence)
    /mcp         MCP server endpoint (streamable-http)

Local:
    python app.py
Production:
    PORT=8000 python app.py
"""

from __future__ import annotations

import os

import uvicorn

from demo_app import app

if __name__ == "__main__":
    uvicorn.run(
        app,
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8000")),
        log_level=os.getenv("LOG_LEVEL", "info"),
    )
