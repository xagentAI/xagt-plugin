# -*- coding: utf-8 -*-
"""Fetch unified diffs from GitHub PR / commit URLs.

Supports:
- https://github.com/{owner}/{repo}/pull/{number}
- https://github.com/{owner}/{repo}/pull/{number}.diff
- https://github.com/{owner}/{repo}/commit/{sha}
- https://github.com/{owner}/{repo}/commit/{sha}.diff
- https://patch-diff.githubusercontent.com/raw/{owner}/{repo}/pull/{number}.diff

Public repos need no token. Private repos read GITHUB_TOKEN from the env.
Uses only the standard library — no extra dependency.
"""
from __future__ import annotations

import os
import re
import urllib.error
import urllib.request

_PR_RE = re.compile(
    r"^https?://github\.com/([^/]+)/([^/]+)/pull/(\d+)(?:\.diff)?/?$"
)
_COMMIT_RE = re.compile(
    r"^https?://github\.com/([^/]+)/([^/]+)/commit/([0-9a-f]+)(?:\.diff)?/?$"
)
_PATCH_DIFF_RE = re.compile(
    r"^https?://patch-diff\.githubusercontent\.com/raw/([^/]+)/([^/]+)/pull/(\d+)\.diff$"
)

_FETCH_TIMEOUT = 12
_MAX_DIFF_BYTES = 200_000


class FetchError(Exception):
    pass


def normalize_to_diff_url(url: str) -> tuple[str, str]:
    """Convert a GitHub URL to its .diff URL and return (diff_url, description)."""
    url = url.strip()

    m = _PATCH_DIFF_RE.match(url)
    if m:
        return url, f"PR {m.group(1)}/{m.group(2)}#{m.group(3)}"

    m = _PR_RE.match(url)
    if m:
        owner, repo, num = m.group(1), m.group(2), m.group(3)
        diff_url = f"https://github.com/{owner}/{repo}/pull/{num}.diff"
        return diff_url, f"PR {owner}/{repo}#{num}"

    m = _COMMIT_RE.match(url)
    if m:
        owner, repo, sha = m.group(1), m.group(2), m.group(3)
        diff_url = f"https://github.com/{owner}/{repo}/commit/{sha}.diff"
        return diff_url, f"commit {owner}/{repo}@{sha[:7]}"

    raise FetchError(
        "Unsupported URL. Use a GitHub PR or commit URL, e.g. "
        "https://github.com/owner/repo/pull/123 or "
        "https://github.com/owner/repo/commit/<sha>"
    )


def fetch_diff(url: str, token: str | None = None) -> tuple[str, str]:
    """Fetch a unified diff from a GitHub PR/commit URL.

    Returns (diff_text, source_description). Raises FetchError on failure.
    """
    diff_url, description = normalize_to_diff_url(url)
    token = token or os.environ.get("GITHUB_TOKEN", "")

    req = urllib.request.Request(diff_url)
    req.add_header("User-Agent", "code-review-agent")
    req.add_header("Accept", "text/plain, application/x-patch, */*")
    if token:
        req.add_header("Authorization", f"token {token}")

    try:
        with urllib.request.urlopen(req, timeout=_FETCH_TIMEOUT) as resp:
            raw = resp.read(_MAX_DIFF_BYTES + 1)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise FetchError(f"未找到资源（404）：{diff_url}") from exc
        if exc.code in (401, 403):
            raise FetchError(
                f"无访问权限（{exc.code}）。若是私有仓库，请设置 GITHUB_TOKEN 环境变量。"
            ) from exc
        raise FetchError(f"GitHub 返回 HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise FetchError(f"网络请求失败：{exc.reason}") from exc

    if len(raw) > _MAX_DIFF_BYTES:
        raise FetchError(
            f"diff 过大（>{_MAX_DIFF_BYTES // 1024} KB），请使用更小的 PR 或 commit。"
        )

    diff_text = raw.decode("utf-8", errors="replace")
    if not diff_text.strip():
        raise FetchError("拉取到的 diff 为空，可能该 PR/commit 无代码变更。")
    return diff_text, description