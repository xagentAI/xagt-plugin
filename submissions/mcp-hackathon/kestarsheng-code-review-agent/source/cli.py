#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""One-click code review of git changes — no pasting needed.

Usage:
  python cli.py                      Review uncommitted changes (git diff)
  python cli.py --staged             Review staged changes (git diff --cached)
  python cli.py --commit HEAD~1      Review the last commit
  python cli.py --commit HEAD~3      Review the last 3 commits
  python cli.py src/utils.py         Review a single file
  python cli.py --remote             Use remote Vercel deployment
  python cli.py --format json        Output JSON (machine-readable, for pipes/CI)
  python cli.py --sarif out.sarif    Export SARIF (GitHub Code Scanning format)

Exit codes:
  0  No issues or only info/minor
  2  Critical or major issues found (use as CI gate)
  1  Runtime error (git failure, API connection failure, etc.)
"""
import argparse
import json
import os
import subprocess
import sys
import urllib.request

REMOTE_URL = "https://code-review-agent-ashy-six.vercel.app"
LOCAL_URL = "http://127.0.0.1:8000"

_LANG_MAP = {
    ".py": "python", ".js": "javascript", ".ts": "javascript",
    ".jsx": "javascript", ".tsx": "javascript",
    ".java": "java", ".go": "go", ".rs": "rust",
    ".rb": "ruby", ".php": "php", ".c": "c", ".cpp": "c",
    ".sh": "shell", ".bash": "shell",
}


def detect_lang(filepath: str) -> str:
    ext = os.path.splitext(filepath)[1].lower()
    return _LANG_MAP.get(ext, "")


def run_git(*args) -> str:
    result = subprocess.run(
        ["git"] + list(args), capture_output=True, text=True, encoding="utf-8"
    )
    if result.returncode != 0:
        print(f"git error: {result.stderr.strip()}", file=sys.stderr)
        sys.exit(1)
    return result.stdout


def get_diff(staged: bool, commit: str | None) -> str:
    if commit:
        return run_git("diff", commit)
    if staged:
        return run_git("diff", "--cached")
    return run_git("diff")


def call_api(base_url: str, endpoint: str, payload: dict) -> dict:
    url = base_url + endpoint
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"API error {e.code}: {body}", file=sys.stderr)
        sys.exit(1)
    except urllib.error.URLError as e:
        print(f"Connection failed: {e}\nPlease start the service first: uvicorn app.main:app", file=sys.stderr)
        sys.exit(1)


SEVERITY_ICON = {"critical": "🔴", "major": "🟠", "minor": "🟡", "info": "🔵"}
SOURCE_ICON = {"rule": "⚡", "llm": "🧠", "confirmed": "✅"}


def print_report(data: dict, is_diff: bool):
    if not data.get("ok"):
        print(f"❌ {data.get('error', 'Unknown error')}")
        return

    report = data.get("report", {})
    score = report.get("score", 0)
    grade = report.get("grade", "?")
    dims = report.get("dimension_scores", {})

    print(f"\n{'='*60}")
    print(f"  Score: {score}/100 (grade {grade})")
    if dims:
        dim_labels = {
            "correctness": "Correctness", "security": "Security",
            "performance": "Performance", "maintainability": "Maintainability",
            "best_practice": "Best Practice",
        }
        dim_str = "  ".join(f"{dim_labels[k]}:{v}" for k, v in dims.items() if k in dim_labels)
        print(f"  {dim_str}")

    if is_diff and "files_changed" in data:
        files = data.get("files_changed", [])
        print(f"  Changes: {', '.join(files)}  +{data.get('added_lines',0)} -{data.get('removed_lines',0)}")

    info = report.get("engine_info", {})
    if info:
        print(f"  Engine: Rules={info.get('rule_count',0)} LLM={info.get('llm_count',0)} Confirmed={info.get('confirmed_count',0)}")

    print(f"{'='*60}\n")

    summary = report.get("summary", "")
    if summary:
        print(f"📋 {summary}\n")

    issues = report.get("issues", [])
    if not issues:
        print("✅ No issues found\n")
        return

    print(f"Found {len(issues)} issues:\n")
    for i in issues:
        sev = i.get("severity", "info")
        src = i.get("source", "llm")
        line = f"L{i['line']}" if i.get("line") else "?"
        icon = SEVERITY_ICON.get(sev, "•")
        sicon = SOURCE_ICON.get(src, "")
        rule = f" [{i['rule_id']}]" if i.get("rule_id") else ""
        print(f"  {icon} {sicon} {i.get('title', '')} ({line}){rule}")
        print(f"     {i.get('description', '')[:120]}")
        if i.get("fix_code"):
            print(f"     🔧 Fix: {i['fix_code'][:100]}")
        print()

    strengths = report.get("strengths", [])
    if strengths:
        print("👍 Strengths:")
        for s in strengths[:3]:
            print(f"  • {s}")
        print()


def to_sarif(data: dict) -> dict:
    report = data.get("report", {})
    issues = report.get("issues", [])
    sev_map = {"critical": "error", "major": "error", "minor": "warning", "info": "note"}
    results = []
    for i in issues:
        results.append({
            "ruleId": str(i.get("rule_id") or "llm"),
            "level": sev_map.get(i.get("severity", "info"), "note"),
            "message": {"text": str(i.get("title", "")) + " — " + str(i.get("description", ""))},
            "locations": [{
                "physicalLocation": {
                    "artifactLocation": {"uri": str(i.get("file", "reviewed"))},
                    "region": {"startLine": int(i.get("line", 1))},
                }
            }],
        })
    return {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [{
            "tool": {"driver": {"name": "Code Review Agent", "version": "1.0"}},
            "results": results,
        }],
    }


def get_exit_code(data: dict) -> int:
    if not data.get("ok"):
        return 1
    issues = data.get("report", {}).get("issues", [])
    for i in issues:
        if i.get("severity") in ("critical", "major"):
            return 2
    return 0


def main():
    parser = argparse.ArgumentParser(description="One-click code review")
    parser.add_argument("--staged", action="store_true", help="Review staged changes")
    parser.add_argument("--commit", metavar="REF", help="Review changes in specified commit (e.g. HEAD~1)")
    parser.add_argument("--remote", action="store_true", help="Use remote Vercel deployment")
    parser.add_argument("--url", metavar="URL", help="Custom API URL")
    parser.add_argument("--format", choices=["table", "json"], default="table", help="Output format")
    parser.add_argument("--sarif", metavar="FILE", help="Export SARIF format to file")
    parser.add_argument("file", nargs="?", help="Review a single file")
    args = parser.parse_args()

    base = args.url or (REMOTE_URL if args.remote else LOCAL_URL)

    if args.file:
        if not os.path.exists(args.file):
            print(f"File not found: {args.file}", file=sys.stderr)
            sys.exit(1)
        code = open(args.file, "r", encoding="utf-8").read()
        lang = detect_lang(args.file)
        if args.format == "table":
            print(f"Reviewing file: {args.file} ({lang or 'unknown'})")
        data = call_api(base, "/v1/review", {"code": code, "language": lang})
        is_diff = False
    else:
        diff = get_diff(args.staged, args.commit)
        if not diff.strip():
            print("No changes detected.")
            return
        if args.format == "table":
            line_count = diff.count("\n")
            print(f"Reviewing diff: {line_count} lines changed")
        data = call_api(base, "/v1/review_diff", {"diff": diff})
        is_diff = True

    if args.sarif:
        sarif = to_sarif(data)
        with open(args.sarif, "w", encoding="utf-8") as f:
            json.dump(sarif, f, ensure_ascii=False, indent=2)
        if args.format == "table":
            print(f"SARIF exported to {args.sarif}")

    if args.format == "json":
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print_report(data, is_diff=is_diff)

    sys.exit(get_exit_code(data))


if __name__ == "__main__":
    main()
