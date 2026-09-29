"""
real_agent_task.py · finish a real task with the tools MCPForge generates

Task: a technology selection brief — find the most popular MCP-related projects on GitHub and verify their
live metrics (stars / forks / open issues / primary language / last update), then output a decision-ready brief.

Why this is a real task rather than a prompt demo:
  1. The conclusion depends on live data. Stars, issue counts, and last-update timestamps change daily,
     so an LLM recalling training data cannot produce real values — the tools have to be called.
  2. It needs multiple tool calls: search candidates → verify each → rank → produce the brief.
     A single-step probe cannot do this, which is what "the tools can really be orchestrated by an agent" means.
  3. Every step is real HTTP and checkable: status_code / latency / usage / billing are all recorded.

Usage: NO_PROXY=* .venv/Scripts/python.exe examples/real_agent_task.py
Output: examples/real_agent_task_result.json (checkable evidence)
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import core  # noqa: E402
import metering  # noqa: E402

SPEC = str(HERE / "github-openapi.json")
OUT = HERE / "real_agent_task_result.json"
API_NAME = "github_live"
TOPIC = "model-context-protocol"
TOP_N = 3


def _brief_item(repo: dict) -> dict:
    """Extract the fields a decision needs from a repository payload, instead of dumping the whole response into the model."""
    return {
        "full_name": repo.get("full_name"),
        "stars": repo.get("stargazers_count"),
        "forks": repo.get("forks_count"),
        "open_issues": repo.get("open_issues_count"),
        "language": repo.get("language"),
        "pushed_at": repo.get("pushed_at"),
        "description": (repo.get("description") or "")[:120],
    }


async def main() -> None:
    result: dict = {"task": f"produce a technology selection brief for {TOPIC!r}", "topic": TOPIC}

    # 1) VERIFY — real calls; only 2xx counts as passed
    verify = await core.verify_api_async(SPEC, max_ops=20)
    result["verify"] = {
        "total_operations": verify["total_operations"],
        "filtered_operations": verify["filtered_operations"],
        "passed": verify["passed"],
        "verified": verify["verified"],
        "verdict": verify["verdict"],
        "detail": [
            {"operation_id": r["operation_id"], "http_status": r["http_status"],
             "passed": r["passed"], "latency_ms": r["latency_ms"]}
            for r in verify["results"]
        ],
    }

    # 2) REGISTER — register into the registry to get orchestratable tools
    await core._registry.register_async(API_NAME, SPEC)

    # 3) Step one: search for candidates
    search = await core._registry.call_async(
        API_NAME, "searchRepositories",
        {"q": TOPIC, "sort": "stars", "order": "desc", "per_page": 5},
    )
    items = (search.get("data") or {}).get("items") or []
    candidates = [
        {"full_name": it.get("full_name"), "stars_at_search": it.get("stargazers_count")}
        for it in items[:TOP_N]
    ]
    result["step1_search"] = {
        "status_code": search.get("status_code"),
        "ok": search.get("ok"),
        "returned": len(items),
        "data_truncated": search.get("data_truncated"),
        "candidates": candidates,
    }

    # 4) Step two: verify live metrics one by one (search summaries go stale, so go back to the source)
    verified_repos = []
    for c in candidates:
        fn = c.get("full_name") or ""
        if "/" not in fn:
            continue
        owner, repo = fn.split("/", 1)
        r = await core._registry.call_async(
            API_NAME, "getRepository", {"owner": owner, "repo": repo}
        )
        data = r.get("data") or {}
        verified_repos.append({
            "status_code": r.get("status_code"),
            "ok": r.get("ok"),
            **_brief_item(data),
        })
    verified_repos.sort(key=lambda x: (x.get("stars") or 0), reverse=True)
    result["step2_verify_details"] = verified_repos

    # 5) Step three: aggregate the brief
    result["brief"] = {
        "generated_from": "live GitHub API (not model memory)",
        "top_pick": (verified_repos[0]["full_name"] if verified_repos else None),
        "ranking": [
            {"rank": i + 1, **v} for i, v in enumerate(verified_repos)
        ],
    }

    # 6) MONETIZE — real usage and billing
    report = metering.get_meter().report(API_NAME)
    api_usage = (report.get("apis") or {}).get(API_NAME) or {}
    result["usage_report"] = report
    # Actual basis: how many calls really happened and how the tier prices them
    result["invoice_actual"] = metering.get_meter().simulate_invoice(
        API_NAME, pricing_tier="pro", basis="actual"
    )
    # Scaled basis: demo volume sits far below the free quota, so the actual invoice is necessarily 0;
    # showing only that one makes monetization look broken, so also model revenue at 1M calls/month.
    result["invoice_scaled"] = metering.get_meter().simulate_invoice(
        API_NAME, pricing_tier="pro", projected_calls=1_000_000
    )

    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[task] {result['task']}")
    print(f"[VERIFY] {verify['passed']}/{verify['filtered_operations']} passed -> {verify['verdict']}")
    for v in verified_repos:
        print(f"  - {v['full_name']}: ★{v['stars']} forks={v['forks']} "
              f"issues={v['open_issues']} lang={v['language']}")
    act = result["invoice_actual"]
    scaled = result["invoice_scaled"]
    print(f"[billing] actual {api_usage.get('total_calls')} calls -> {act.get('amount_due')} "
          f"{act.get('currency')} (free quota of {act.get('included_calls')} calls not exhausted)")
    print(f"[billing] scaled 1M calls/month -> {scaled.get('amount_due')} {scaled.get('currency')}")
    print(f"[OK] evidence written to {OUT}")


if __name__ == "__main__":
    asyncio.run(main())
