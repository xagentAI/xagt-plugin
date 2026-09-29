"""Reviewer on-site check script · MCPForge

Purpose: with one command and no setup (beyond an MCP client library), verify three hard facts about this submission —
  1. the entry is genuinely callable (the gate is that the wrapped API really responds, not merely "deployed publicly")
  2. it exposes a **really callable MCP endpoint**, not an HTTP shell with nothing but a health check
  3. all 7 tool names from the delivery spec are present, and section 6 acceptance items #2/#3 (generate deployable code; register then call by operation_id) actually run

Design principles (no deployment needed, reproducible offline):
  - the service starts as one local process (uvicorn demo_app:app); one command reviews it, no public deployment required
  - parse / generate / list checks run against local fixtures (offline-api.json) and never touch the network
  - only the two "real outbound" checks call the GitHub public REST API
    (reachable from the sandbox, keyless), honestly showing whether an agent can really call the API

Run:
    pip install "fastmcp>=4.0,<5.0"
    python docs/judge_check.py
    python docs/judge_check.py --url http://127.0.0.1:8000

Exit code 0 means everything passed; non-zero means something failed, with the reason printed.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

DEFAULT_URL = "http://127.0.0.1:8000"

# Local offline fixture shaped like Petstore (including getPetById): the parse, generate, and list-tool checks
# all run against local files with no network, so a reviewer can reproduce them in any offline environment.
_HERE = Path(__file__).resolve().parent
OFFLINE_SPEC = str((_HERE.parent / "tests" / "fixtures" / "offline-api.json").resolve())
# A real, keyless, sandbox-reachable public API (GitHub public REST API) backs the two hard gates:
# "real outbound" and "register + real call". With no local outbound access those two FAIL honestly
# instead of faking a pass.
GITHUB_SPEC = str((_HERE.parent / "examples" / "github-openapi.json").resolve())
GITHUB_BASE = "https://api.github.com"
GITHUB_ZEN_PATH = "/zen"
GITHUB_ZEN_OP = "getZen"

# The 7 tool names from delivery spec section 4 must match exactly
CONTRACT_TOOLS = [
    "call_rest_api",
    "parse_openapi_spec",
    "list_operations",
    "generate_mcp_tool_code",
    "register_api_from_spec",
    "call_registered_api",
    "health_check",
]


class Report:
    def __init__(self) -> None:
        self.ok = 0
        self.bad = 0

    def check(self, passed: bool, title: str, detail: str = "") -> bool:
        line = f"[{'PASS' if passed else 'FAIL'}] {title}"
        if detail:
            line += f" — {detail}"
        print(line)
        if passed:
            self.ok += 1
        else:
            self.bad += 1
        return passed


def _as_dict(data) -> dict:
    return data if isinstance(data, dict) else {}


async def run(url: str) -> int:
    import httpx
    from fastmcp import Client

    report = Report()
    url = url.rstrip("/")
    mcp_url = f"{url}/mcp/"

    print(f"target instance: {url}")
    print("-" * 72)

    # ---------- 1. HTTP layer: the service is up ----------
    try:
        async with httpx.AsyncClient(timeout=30, trust_env=False) as http:
            r = await http.get(f"{url}/api/health")
            body = _as_dict(r.json()) if r.status_code == 200 else {}
            report.check(
                r.status_code == 200 and body.get("status") == "ok",
                "health check GET /api/health",
                f"HTTP {r.status_code} status={body.get('status')} version={body.get('version')}",
            )

            r = await http.get(f"{url}/")
            report.check(
                r.status_code == 200 and len(r.text) > 1000,
                "four-stage walkthrough page GET /",
                f"HTTP {r.status_code} {len(r.text)} bytes",
            )

            r = await http.get(f"{url}/api/config")
            cfg = _as_dict(r.json()) if r.status_code == 200 else {}
            tiers = cfg.get("pricing_tiers") or {}
            report.check(
                r.status_code == 200 and len(tiers) >= 2,
                "pricing tiers readable (MONETIZE has a real pricing basis) GET /api/config",
                f"tiers={list(tiers)} currency={cfg.get('currency')}",
            )
    except Exception as exc:  # noqa: BLE001
        report.check(False, "HTTP layer reachable", f"{type(exc).__name__}: {exc}")
        return _finish(report)

    # ---------- 2. MCP layer: real endpoint, real tools, real calls ----------
    try:
        async with Client(mcp_url) as client:
            tools = await client.list_tools()
            names = {t.name for t in tools}
            report.check(len(names) >= 7, "MCP endpoint lists tools", f"{len(names)} tools")

            missing = [n for n in CONTRACT_TOOLS if n not in names]
            report.check(
                not missing,
                "all 7 spec-named tools are present",
                "complete" if not missing else f"missing {missing}",
            )

            data = _as_dict((await client.call_tool("health_check", {})).data)
            report.check(
                data.get("status") == "ok",
                "tool call: health_check",
                f"status={data.get('status')}",
            )

            data = _as_dict((await client.call_tool("parse_openapi_spec", {"spec_source": OFFLINE_SPEC})).data)
            count = data.get("operation_count") or 0
            report.check(
                count > 0,
                "tool call: parse_openapi_spec on a local Petstore-style spec",
                f"{count} operations, auth schemes={[s.get('name') for s in (data.get('auth_schemes') or [])]}",
            )

            text = (await client.call_tool("list_operations", {"spec_source": OFFLINE_SPEC})).data
            text = text if isinstance(text, str) else str(text)
            report.check(
                "getPetById" in text,
                "tool call: list_operations returns a readable inventory",
                f"{len(text)} chars, contains getPetById={'getPetById' in text}",
            )

            data = _as_dict(
                (
                    await client.call_tool(
                        "call_rest_api",
                        {
                            "base_url": GITHUB_BASE,
                            "path": GITHUB_ZEN_PATH,
                            "method": "GET",
                        },
                    )
                ).data
            )
            code = data.get("status_code")
            report.check(
                code == 200,
                "tool call: call_rest_api, real outbound (GitHub public REST API)",
                f"HTTP {code}, {data.get('latency_ms')} ms",
            )

            # section 6 acceptance #2: generate_mcp_tool_code(..., "getPetById") → deployable source
            raw = (await client.call_tool(
                "generate_mcp_tool_code",
                {"spec_source": OFFLINE_SPEC, "operation_id": "getPetById"},
            )).data
            code_src = raw if isinstance(raw, str) else str(raw)
            report.check(
                "FastMCP" in code_src and ("get_pet_by_id" in code_src or "getPetById" in code_src),
                "tool call: generate_mcp_tool_code produced deployable FastMCP source (section 6 #2)",
                f"{len(code_src.splitlines())} lines, contains FastMCP and get_pet_by_id",
            )

            # section 6 acceptance #3: register_api_from_spec + call_registered_api(name, op) → real response
            # uses the real, sandbox-reachable, keyless GitHub public REST API to prove it is "callable once registered".
            reg = _as_dict((await client.call_tool(
                "register_api_from_spec",
                {"name": "judge_check_demo", "spec_source": GITHUB_SPEC},
            )).data)
            call = _as_dict((await client.call_tool(
                "call_registered_api",
                {"name": "judge_check_demo", "operation_id": GITHUB_ZEN_OP},
            )).data)
            report.check(
                call.get("status_code") == 200,
                f"tool call: register + call_registered_api({GITHUB_ZEN_OP}) real outbound (section 6 #3)",
                f"register ops={reg.get('operations')} | call HTTP {call.get('status_code')}",
            )
    except Exception as exc:  # noqa: BLE001
        report.check(False, "MCP layer call", f"{type(exc).__name__}: {exc}")

    return _finish(report)


def _finish(report: Report) -> int:
    print("-" * 72)
    print(f"result: {report.ok} passed / {report.bad} failed")
    return 0 if report.bad == 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="MCPForge reviewer on-site check")
    parser.add_argument("--url", default=DEFAULT_URL, help="root URL of the instance under review")
    args = parser.parse_args()
    return asyncio.run(run(args.url))


if __name__ == "__main__":
    sys.exit(main())
