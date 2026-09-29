"""构建 X-Agent MCP Hackathon 提交快照并做离线预检（纯标准库）。

做什么：
  1. 取当前 git HEAD 的 40 位 SHA 作为 reviewCommit；
  2. 用 `git archive HEAD` 把【已提交的源码】原样导出到 source/（不含 .git、
     未跟踪文件、.env，天然满足"评审基线 = pinned commit"）；
  3. 拷贝 SUBMISSION.md / RIGHTS.md / verification/，渲染 submission.json；
  4. 按官方 scripts/validate-submission.mjs 的同等规则做离线预检
     （结构、manifest、文件大小/数量、密钥特征、curl 证据）；
  5. --online 时额外校验：GitHub commit 可公开访问、线上 health/proof 与
     reviewCommit、slug 三处一致。

用法：
  python scripts/build_xagent_submission.py            # 构建 + 离线预检
  python scripts/build_xagent_submission.py --online   # 再加线上一致性校验

产物：dist/xagent-submission/yai-agent-core/（dist/ 已 gitignore）。
提交时把该目录整体复制到 xagt-plugin 仓库的 submissions/mcp-hackathon/ 下提 PR。
"""

from __future__ import annotations

import argparse
import io
import json
import re
import shutil
import subprocess
import tarfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SLUG = "yai-agent-core"
META_DIR = ROOT / "submissions" / "mcp-hackathon" / SLUG
OUT_ROOT = ROOT / "dist" / "xagent-submission"
OUT_DIR = OUT_ROOT / SLUG

# 下面这组常量与官方 validate-submission.mjs 对齐（2026-09 核对）。
MAX_FILES = 2000
MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_TOTAL_BYTES = 20 * 1024 * 1024
SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
SHA_RE = re.compile(r"^[a-f0-9]{40}$")
FORBIDDEN_DIRS = {"node_modules", ".git", "dist", "build", ".next"}
IMPL_EXT_RE = re.compile(
    r"\.(?:[cm]?[jt]sx?|py|go|rs|java|kt|kts|c|cc|cpp|h|hpp|cs|fs|rb|php|swift"
    r"|scala|sh|bash|sol|vy|ex|exs|erl|clj|lua|r|jl|ipynb|html|vue|svelte|sql)$",
    re.IGNORECASE,
)
SECRET_PATTERNS = [
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b"),
]


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.strip()


def fail(msg: str) -> None:
    raise SystemExit(f"[预检失败] {msg}")


def build() -> str:
    sha = git("rev-parse", "HEAD")
    if not SHA_RE.match(sha):
        fail(f"HEAD 不是合法 40 位 SHA：{sha!r}")

    # 工作区未提交改动只警告：评审基线是已推送的 commit，快照里不会带上这些改动。
    dirty = git("status", "--porcelain")
    if dirty:
        print("[警告] 工作区有未提交改动，不会进入快照（git archive 只取 HEAD）：")
        for line in dirty.splitlines()[:10]:
            print("   ", line)

    if OUT_ROOT.exists():
        shutil.rmtree(OUT_ROOT)
    (OUT_DIR / "verification").mkdir(parents=True)

    # 1) 元数据文件
    for fname in ("SUBMISSION.md", "RIGHTS.md"):
        shutil.copy2(META_DIR / fname, OUT_DIR / fname)
    shutil.copy2(
        META_DIR / "verification" / "README.md",
        OUT_DIR / "verification" / "README.md",
    )

    # 2) 渲染 submission.json（把 __REVIEW_COMMIT__ 换成 HEAD SHA）
    template = json.loads((META_DIR / "submission.template.json").read_text("utf-8"))
    template["reviewCommit"] = sha
    (OUT_DIR / "submission.json").write_text(
        json.dumps(template, ensure_ascii=False, indent=2) + "\n", "utf-8"
    )

    # 3) git archive 导出 pinned commit 的完整源码到 source/
    tar_bytes = subprocess.run(
        ["git", "archive", "--format=tar", "HEAD"],
        cwd=ROOT, capture_output=True, check=True,
    ).stdout
    source_dir = OUT_DIR / "source"
    with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r:") as tar:
        # 安全：拒绝绝对路径与 .. 路径（git archive 不会有，双保险）
        for member in tar.getmembers():
            if member.name.startswith(("/",)) or ".." in Path(member.name).parts:
                fail(f"归档内出现非法路径：{member.name}")
        tar.extractall(source_dir, filter="data")  # py3.12+ 的 data 过滤更安全

    print(f"[构建] reviewCommit = {sha}")
    print(f"[构建] 快照目录 = {OUT_DIR}")
    return sha


def preflight_offline() -> dict:
    """镜像官方校验器的离线检查（不含网络）。"""
    checks: list[str] = []

    # --- 必备文件 ---
    required = ["submission.json", "SUBMISSION.md", "RIGHTS.md",
                "verification/README.md"]
    for rel in required:
        p = OUT_DIR / rel
        if not p.is_file() or p.stat().st_size == 0:
            fail(f"{rel} 缺失或为空")
    checks.append("必备文件齐全且非空")

    # --- manifest ---
    manifest = json.loads((OUT_DIR / "submission.json").read_text("utf-8"))
    if manifest.get("schemaVersion") != 1:
        fail("submission.json schemaVersion 必须为 1")
    if manifest.get("slug") != SLUG or not SLUG_RE.match(SLUG):
        fail("slug 非法或与目录名不一致")
    for key in ("name", "slug", "sourceRepository", "reviewCommit", "apiBaseUrl",
                "healthCheckUrl", "deploymentProofUrl"):
        if not isinstance(manifest.get(key), str) or not manifest[key].strip():
            fail(f"submission.json 缺少字段 {key}")
    if not SHA_RE.match(manifest["reviewCommit"]):
        fail("reviewCommit 必须是 40 位 SHA")
    if not re.match(r"^https://github\.com/[^/]+/[^/]+/?$", manifest["sourceRepository"]):
        fail("sourceRepository 必须是公开的 https github 仓库 URL")
    for key in ("apiBaseUrl", "healthCheckUrl", "deploymentProofUrl"):
        url = manifest[key]
        if not url.startswith("https://") or "localhost" in url:
            fail(f"{key} 必须是公网 HTTPS URL")
    origins = {re.match(r"https://[^/]+", manifest[k]).group(0) for k in
               ("apiBaseUrl", "healthCheckUrl", "deploymentProofUrl")}
    if len(origins) != 1:
        fail("API / health / deployment-proof 必须同源")
    if not manifest["deploymentProofUrl"].endswith("/.well-known/xagent-verification.json"):
        fail("deploymentProofUrl 路径必须是 /.well-known/xagent-verification.json")
    checks.append("submission.json 结构与 URL 契约合法")

    # --- 遍历 source/：大小、数量、禁目录、实现文件、密钥扫描 ---
    total = 0
    count = 0
    has_impl = False
    for path in sorted((OUT_DIR / "source").rglob("*")):
        if path.is_symlink():
            fail(f"不允许符号链接：{path.relative_to(OUT_DIR)}")
        if path.is_dir():
            if path.name in FORBIDDEN_DIRS:
                fail(f"不允许的目录：{path.relative_to(OUT_DIR)}")
            continue
        rel = path.relative_to(OUT_DIR).as_posix()
        count += 1
        size = path.stat().st_size
        total += size
        if size > MAX_FILE_BYTES:
            fail(f"单文件超过 5MiB：{rel}")
        if total > MAX_TOTAL_BYTES:
            fail("源码总体积超过 20MiB")
        if count > MAX_FILES:
            fail("文件数超过 2000")
        if IMPL_EXT_RE.search(rel):
            has_impl = True
        name = path.name.lower()
        if name.startswith(".env") and "example" not in name:
            fail(f"疑似密钥文件：{rel}")
        if re.search(r"\.(pem|p12|pfx|key)$", name):
            fail(f"疑似密钥文件类型：{rel}")
        try:
            text = path.read_text("utf-8")
        except (UnicodeDecodeError, PermissionError):
            continue  # 二进制文件跳过文本特征扫描
        for pat in SECRET_PATTERNS:
            if pat.search(text):
                fail(f"命中密钥特征 {pat.pattern}：{rel}")
    if not has_impl:
        fail("source/ 内没有实现文件")
    checks.append(f"source/ 共 {count} 个文件、{total/1024:.0f} KiB，无禁目录/密钥特征")

    # --- verification 证据 ---
    ver = (OUT_DIR / "verification" / "README.md").read_text("utf-8")
    if not re.search(r"curl\s", ver) or "health" not in ver:
        fail("verification/README.md 必须包含可复现 curl 命令与 health 证据")
    checks.append("verification/README.md 含 curl 与 health 证据")

    print("[离线预检] 全部通过：")
    for c in checks:
        print("   ✓", c)
    return manifest


def http_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "yai-submission-check",
                                               "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 - 固定官方 URL
        return json.loads(resp.read().decode("utf-8"))


def preflight_online(manifest: dict) -> None:
    sha = manifest["reviewCommit"]
    # 1) GitHub commit 必须可公开访问
    owner_repo = manifest["sourceRepository"].removeprefix("https://github.com/").strip("/")
    commit_url = f"https://api.github.com/repos/{owner_repo}/commits/{sha}"
    try:
        http_json(commit_url)
        print("[线上预检] ✓ GitHub 上可公开验证 reviewCommit")
    except Exception as exc:  # noqa: BLE001
        fail(f"GitHub commit 不可公开验证：{exc}")

    # 2) health：status 健康且 commit 一致
    health = http_json(manifest["healthCheckUrl"])
    health_commit = health.get("commit") or health.get("version")
    if health.get("status") not in ("ok", "healthy"):
        fail(f"health status 非 ok/healthy：{health.get('status')!r}")
    if health_commit != sha:
        fail(
            f"health commit {health_commit!r} != reviewCommit {sha!r}"
            "（是否忘了等部署完成，或正式提交时没关 autoDeploy？）"
        )
    print("[线上预检] ✓ /health 在线且 commit 与 reviewCommit 一致")

    # 3) deployment proof：schemaVersion / slug / commit 一致
    proof = http_json(manifest["deploymentProofUrl"])
    if (proof.get("schemaVersion") != 1 or proof.get("slug") != manifest["slug"]
            or proof.get("commit") != sha):
        fail(f"部署证明不一致：{proof}")
    print("[线上预检] ✓ /.well-known/xagent-verification.json 的 slug/commit 一致")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--online", action="store_true", help="额外做线上一致性校验")
    args = parser.parse_args()

    build()
    manifest = preflight_offline()
    if args.online:
        preflight_online(manifest)
    print(
        "\n[下一步] 1) 确认该 commit 已推送且线上部署完成（正式提交时在 Render 关 autoDeploy）；\n"
        "        2) fork https://github.com/xagentAI/xagt-plugin ；\n"
        "        3) 把 dist/xagent-submission/yai-agent-core 整个目录复制到\n"
        "           fork 的 submissions/mcp-hackathon/ 下；\n"
        "        4) 提 PR（只动这一个目录），PR 描述按官方模板勾选确认项。"
    )


if __name__ == "__main__":
    main()
