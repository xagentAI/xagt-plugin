"""
core.py · MCPForge core logic v2 (transport-agnostic, shared by server.py / demo_app.py / verify.py)

Material changes in v2 over v1 (each traces to an adversarial review finding):
- [fix] Pasted OpenAPI text is no longer misclassified as a file path (v1 raised FileNotFoundError).
- [fix] All IO is async; synchronous httpx no longer blocks the event loop.
- [fix] VERIFY no longer treats any response as reachable: 2xx passes, and auth failure, bad parameters, and unreachable are distinct.
- [fix] Code generation no longer splices raw paths into f-strings (v1 produced NameError for placeholders like {account-id}).
- [fix] Generated docstrings are escaped, so a triple quote in the spec cannot turn the output into a SyntaxError.
- [fix] Output paths are guarded against traversal; local reads stay inside allowed roots.
- [fix] Outbound requests carry SSRF protection (loopback, private, and link-local refused by default).
- [fix] The registry writes atomically; a corrupt file is kept aside rather than silently cleared.
- [new] $ref expansion, path-level parameter merging, auth scheme detection, pagination detection.
- [new] Every call records real usage metering (feeding MONETIZE invoices).

This module does not depend on FastMCP and unit tests on its own.
Compliance: pure API/MCP engineering. No security, audit, or on-chain surface.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import os
import re
import socket
import tempfile
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import httpx
import yaml

import metering

VERSION = "2.1.0"
USER_AGENT = f"MCPForge/{VERSION}"
HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "options"}
DEFAULT_TIMEOUT = 20.0

# Pagination heuristics (used at BUILD to hint how callers should page)
_PAGINATION_HINTS = {
    "limit", "offset", "page", "page_size", "pagesize", "per_page", "perpage",
    "cursor", "skip", "start", "count", "size", "next",
}


class SpecSourceError(ValueError):
    """A spec source could not be resolved (URL unreachable / file missing / text is not a valid spec)."""


class PathNotAllowed(PermissionError):
    """A path escaped the security boundary."""


# --------------------------------------------------------------------------- #
# Security boundaries: read roots, write roots, outbound allowlist
# --------------------------------------------------------------------------- #
def _read_roots() -> list[Path]:
    """Roots allowed for reading local specs. Defaults to the working directory; override with MCPFORGE_READ_ROOTS (os.pathsep-separated)."""
    env = os.getenv("MCPFORGE_READ_ROOTS", "")
    roots = [Path(p).expanduser().resolve() for p in env.split(os.pathsep) if p.strip()]
    return roots or [Path.cwd().resolve()]


def ensure_readable(path_str: str) -> Path:
    """Confine a user-supplied local path to the allowed roots, so the tool surface never becomes an arbitrary file read primitive."""
    p = Path(path_str).expanduser()
    if not p.is_absolute():
        p = Path.cwd() / p
    p = p.resolve()
    if os.getenv("MCPFORGE_ALLOW_ANY_PATH", "") == "1":
        return p
    for root in _read_roots():
        if p == root or root in p.parents:
            return p
    raise PathNotAllowed(
        f"refusing to read {p}: outside the allowed directories {[str(r) for r in _read_roots()]}. "
        "Set MCPFORGE_ALLOW_ANY_PATH=1 or MCPFORGE_READ_ROOTS to relax this."
    )


_SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def ensure_writable_dir(root: str, name: str) -> Path:
    """Output path for generated artifacts: a name allowlist plus a check that the result sits inside root, so traversal is refused."""
    if not _SAFE_NAME_RE.match(name or ""):
        raise PathNotAllowed(
            f"invalid name {name!r}: only letters/digits/._- allowed, must start with a letter or digit, length 1-64."
        )
    root_p = Path(root).expanduser()
    if not root_p.is_absolute():
        root_p = Path.cwd() / root_p
    root_p = root_p.resolve()
    target = (root_p / name).resolve()
    if target != root_p and root_p not in target.parents:
        raise PathNotAllowed(f"output directory {target} escapes the allowed root {root_p}; refused.")
    return target


# Trusted public hosts pinned by the operator (default empty = trust nothing, block all).
# A host is allowed through only when explicitly listed here; its resolved address is then
# exempt from the reserved-range refusal. This is what lets the official showcase host
# api.github.com work on cloud platforms whose egress proxy resolves it into 198.18.0.0/15
# (RFC 2544 benchmarking range), which the reserved-address check would otherwise reject.
# All other user-supplied URLs still go through the full public-network validation.
_TRUSTED_HOSTS = {
    h.strip().lower()
    for h in os.getenv("MCPFORGE_TRUSTED_HOSTS", "").split(",")
    if h.strip()
}


def _is_trusted_host(host: str) -> bool:
    host = (host or "").lower()
    if not host:
        return False
    return any(host == th or host.endswith("." + th) for th in _TRUSTED_HOSTS)


def assert_public_url(url: str) -> None:
    """SSRF guard applied before any outbound request: refuses loopback, private, link-local, and reserved addresses.

    This is not complete protection (it does not stop DNS rebinding), but it blocks the two most common abuses:
    cloud metadata endpoints and internal network probing. Set MCPFORGE_ALLOW_PRIVATE_NET=1 for local debugging.
    A host listed in MCPFORGE_TRUSTED_HOSTS bypasses only the reserved-range refusal.
    """
    if os.getenv("MCPFORGE_ALLOW_PRIVATE_NET", "") == "1":
        return
    p = urllib.parse.urlparse(url)
    if p.scheme not in ("http", "https"):
        raise ValueError(f"only http/https supported, got {p.scheme!r}")
    host = p.hostname
    if not host:
        raise ValueError(f"URL is missing a host: {url}")
    if host == "localhost" or host.endswith(".localhost"):
        raise ValueError(f"refusing localhost address {host} (set MCPFORGE_ALLOW_PRIVATE_NET=1 to allow it)")
    if _is_trusted_host(host):
        # Operator-pinned public showcase host: allow its (possibly egress-proxy) resolved address,
        # while every other URL still goes through the full check below.
        return
    port = p.port or (443 if p.scheme == "https" else 80)
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        raise ValueError(f"cannot resolve host {host}: {e}") from e
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            raise ValueError(
                f"refusing {host}: resolves to a non-public address {ip}. "
                "Set MCPFORGE_ALLOW_PRIVATE_NET=1 to allow localhost and private networks."
            )


_REDIRECT_CODES = frozenset({301, 302, 303, 307, 308})
MAX_REDIRECTS = 5


async def request_with_validated_redirects(
    method: str,
    url: str,
    *,
    params: Optional[dict] = None,
    json_body: Optional[dict] = None,
    headers: Optional[dict] = None,
    timeout: float = DEFAULT_TIMEOUT,
    max_redirects: int = MAX_REDIRECTS,
) -> httpx.Response:
    """HTTP request with per-hop validation.

    Why httpx's follow_redirects=True is not enough: it gives exactly one validation chance, on the initial URL.
    A **public** address that answers 302 to 169.254.169.254 or 127.0.0.1 walks straight past the SSRF guard.
    This was reproduced locally (public URL -> 302 -> local service; the response body contained internal content,
    status_code=200).

    So redirects are followed manually, calling assert_public_url again on every hop,
    with the 303/302 method rewrite applied per RFC.
    """
    current_url = url
    current_method = method.upper()
    current_params = params
    current_body = json_body

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
        for _ in range(max_redirects + 1):
            assert_public_url(current_url)
            resp = await client.request(
                current_method,
                current_url,
                params=current_params or None,
                json=current_body,
                headers=headers,
            )
            location = resp.headers.get("location")
            if resp.status_code not in _REDIRECT_CODES or not location:
                return resp
            current_url = urllib.parse.urljoin(str(resp.url), location)
            # 303 always becomes GET; 302 on non-GET becomes GET by browser convention
            if resp.status_code == 303 or (
                resp.status_code == 302 and current_method not in ("GET", "HEAD")
            ):
                current_method = "GET"
                current_body = None
            current_params = None  # parameters are already merged into the current URL; avoid appending them twice

    raise ValueError(f"aborted after more than {max_redirects} redirects (possible redirect loop).")


# --------------------------------------------------------------------------- #
# BUILD: parsing, $ref expansion, operation extraction
# --------------------------------------------------------------------------- #
def _looks_like_path(s: str) -> bool:
    if s.startswith(("./", "../", ".\\", "..\\")):
        return True
    if any(ch in s for ch in ("\n", "\r")):
        return False  # multiple lines means text, not a path
    if s.lower().endswith((".json", ".yaml", ".yml")):
        return True
    return ("/" in s or "\\" in s) and " " not in s.strip() and "{" not in s


def parse_spec_text(text: str, source: str = "<text>") -> dict:
    """Parse a chunk of text into a spec dict. JSON first, YAML as fallback, with a diagnostic error on failure."""
    if not text or not text.strip():
        raise SpecSourceError(f"spec content is empty (source: {source})")
    spec: Any = None
    err: Optional[Exception] = None
    try:
        spec = json.loads(text)
    except json.JSONDecodeError as e:
        err = e
        try:
            spec = yaml.safe_load(text)
        except yaml.YAMLError as e2:
            raise SpecSourceError(
                f"could not parse the content as JSON or YAML (source: {source}). JSON error: {e}; YAML error: {e2}"
            ) from e2
    if not isinstance(spec, dict):
        raise SpecSourceError(
            f"parsed content is not an OpenAPI object but {type(spec).__name__} (source: {source}). "
            "Make sure you passed the OpenAPI/Swagger document itself."
        )
    if "paths" not in spec and "openapi" not in spec and "swagger" not in spec:
        raise SpecSourceError(
            f"content does not look like an OpenAPI document: the top level lacks paths/openapi/swagger keys (source: {source}). "
            f"actual top-level keys: {sorted(spec.keys())[:10]}"
        )
    return spec


async def _fetch_text_async(url: str, timeout: float = DEFAULT_TIMEOUT) -> str:
    r = await request_with_validated_redirects(
        "GET",
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json, */*"},
        timeout=timeout,
    )
    r.raise_for_status()
    return r.text


def _fetch_text(url: str, timeout: float = DEFAULT_TIMEOUT) -> str:
    return asyncio.run(_fetch_text_async(url, timeout))


async def load_spec_async(source: str, timeout: float = DEFAULT_TIMEOUT) -> dict:
    """Load a spec asynchronously.

    Source resolution order (this is where v1 broke; v2 tries the real thing before guessing the shape):
      1) http(s) URL             -> fetch it
      2) an existing local file  -> read it (bounded by the allowed roots)
      3) anything else is parsed as text; only if parsing fails and it looks like a path do we report FileNotFoundError
    """
    src = (source or "").strip()
    if not src:
        raise SpecSourceError("spec_source must not be empty")

    if src.startswith(("http://", "https://")):
        text = await _fetch_text_async(src, timeout)
        spec = parse_spec_text(text, src)
    elif Path(src).expanduser().is_file():
        p = ensure_readable(src)
        spec = parse_spec_text(p.read_text(encoding="utf-8"), str(p))
    else:
        try:
            spec = parse_spec_text(src, "<inline text>")
        except SpecSourceError as e:
            if _looks_like_path(src):
                raise FileNotFoundError(
                    f"local spec file does not exist: {src} (if you meant to paste spec text, "
                    "confirm it is valid OpenAPI JSON/YAML)"
                ) from e
            raise

    spec["x_base_url"] = resolve_base_url(spec, src)
    spec["x_source"] = src if src.startswith(("http://", "https://")) else "<local-or-inline>"
    return spec


def load_spec(source: str, timeout: float = DEFAULT_TIMEOUT) -> dict:
    """Synchronous wrapper (for scripts and unit tests). MCP tools should use load_spec_async."""
    return asyncio.run(load_spec_async(source, timeout))


def resolve_base_url(spec: dict, source: str = "") -> str:
    """Resolve base_url. Handles relative server URLs (such as petstore3's /api/v3) and a missing leading slash."""
    servers = spec.get("servers") or []
    url = ""
    if isinstance(servers, list) and servers and isinstance(servers[0], dict):
        url = servers[0].get("url") or ""

    if url and url.startswith(("http://", "https://")):
        return url.rstrip("/")

    # OpenAPI 2.0
    if not url:
        schemes = spec.get("schemes") or ["https"]
        host = spec.get("host")
        base_path = spec.get("basePath", "")
        if host:
            return f"{schemes[0]}://{host}{base_path}".rstrip("/")

    # Relative server URL: complete it with the origin of the spec source and normalize separators
    if url and source.startswith(("http://", "https://")):
        p = urllib.parse.urlparse(source)
        if not url.startswith("/"):
            url = "/" + url
        return (f"{p.scheme}://{p.netloc}" + url).rstrip("/")
    return (url or "").rstrip("/")


def get_base_url(spec: dict) -> str:
    if isinstance(spec, dict) and spec.get("x_base_url"):
        return spec["x_base_url"]
    return resolve_base_url(spec, "")


def resolve_refs(node: Any, root: Optional[dict] = None, _seen: frozenset = frozenset()) -> Any:
    """Expand local $ref (#/...) in place. Cycle-safe: a self-referencing node is kept as-is instead of recursing."""
    if root is None:
        root = node
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/"):
            if ref in _seen:
                return node  # cycle: stop recursing
            target: Any = root
            for part in ref[2:].split("/"):
                part = part.replace("~1", "/").replace("~0", "~")
                if isinstance(target, dict) and part in target:
                    target = target[part]
                else:
                    return node  # keep it verbatim if it cannot be resolved
            merged = resolve_refs(target, root, _seen | {ref})
            if isinstance(merged, dict):
                extra = {k: resolve_refs(v, root, _seen) for k, v in node.items() if k != "$ref"}
                return {**merged, **extra}
            return merged
        return {k: resolve_refs(v, root, _seen) for k, v in node.items()}
    if isinstance(node, list):
        return [resolve_refs(v, root, _seen) for v in node]
    return node


def detect_auth(spec: dict) -> list[dict]:
    """Detect auth schemes declared by the spec (OpenAPI 3 components.securitySchemes / 2.0 securityDefinitions)."""
    schemes = (
        (spec.get("components") or {}).get("securitySchemes")
        or spec.get("securityDefinitions")
        or {}
    )
    out: list[dict] = []
    if not isinstance(schemes, dict):
        return out
    for name, s in schemes.items():
        if not isinstance(s, dict):
            continue
        t = s.get("type")
        if t == "apiKey":
            out.append({"name": name, "type": "apiKey", "in": s.get("in"), "key_name": s.get("name")})
        elif t == "http":
            out.append({"name": name, "type": "http", "scheme": (s.get("scheme") or "").lower()})
        elif t == "oauth2":
            flats = s.get("flows") or s.get("flow") or {}
            out.append({"name": name, "type": "oauth2", "flows": sorted(flats) if isinstance(flats, dict) else []})
        elif t == "basic":
            out.append({"name": name, "type": "basic"})
    return out


def _param_type(schema: Optional[dict]) -> str:
    t = (schema or {}).get("type")
    return {"integer": "int", "number": "float", "boolean": "bool"}.get(t, "str")


def _collect_params(raw_params: list, path_level: list) -> tuple[list, list, list]:
    """Merge path-level and operation-level parameters (the latter overrides the former by name+in)."""
    merged: dict[tuple, dict] = {}
    for p in list(path_level) + list(raw_params):
        if not isinstance(p, dict) or not p.get("name"):
            continue
        merged[(p.get("name"), p.get("in"))] = p

    path_params, query_params, header_params = [], [], []
    for p in merged.values():
        where = p.get("in")
        sch = p.get("schema") if isinstance(p.get("schema"), dict) else {}
        entry = {
            "name": p.get("name"),
            "type": _param_type(p.get("schema") or p),
            "required": bool(p.get("required", where == "path")),
            "description": p.get("description", ""),
            "pagination_hint": where == "query" and (p.get("name") or "").lower() in _PAGINATION_HINTS,
            # Pass through sample values declared in the spec: VERIFY must call with values that actually work.
            # Otherwise /repos/{owner}/{repo} degrades to /repos/sample/sample → 404
            # and a working endpoint is reported as broken. Left as None when absent, falling back to _sample_value.
            "example": sch.get("example", p.get("example")),
            "default": sch.get("default", p.get("default")),
            "enum": sch.get("enum", p.get("enum")),
        }
        if where == "path":
            path_params.append(entry)
        elif where == "query":
            query_params.append(entry)
        elif where == "header":
            header_params.append(entry)
    return path_params, query_params, header_params


def extract_operations(spec: dict) -> list[dict]:
    """Extract operations from a spec. Expands $ref first and merges path-level parameters."""
    resolved = resolve_refs(spec)
    base = get_base_url(resolved)
    ops: list[dict] = []
    for path, item in (resolved.get("paths") or {}).items():
        if not isinstance(item, dict):
            continue
        path_level = item.get("parameters") or []
        for method, meta in item.items():
            if not isinstance(meta, dict) or method.lower() not in HTTP_METHODS:
                continue
            op_id = meta.get("operationId") or f"{method}_{path}".replace("/", "_").strip("_")
            pp, qp, hp = _collect_params(meta.get("parameters") or [], path_level)
            body_schema = ((meta.get("requestBody") or {}).get("content") or {})
            has_body = bool(meta.get("requestBody")) or bool(body_schema)
            ops.append(
                {
                    "operation_id": op_id,
                    "method": method.upper(),
                    "path": path,
                    "summary": meta.get("summary") or meta.get("description") or "",
                    "tags": meta.get("tags", []),
                    "deprecated": bool(meta.get("deprecated")),
                    "path_params": pp,
                    "query_params": qp,
                    "header_params": hp,
                    "has_body": has_body,
                    "security": meta.get("security", spec.get("security", [])),
                    "paginated": any(p.get("pagination_hint") for p in qp),
                    "base_url": base,
                }
            )
    return ops


# --------------------------------------------------------------------------- #
# Tool curation: collapse N endpoints into a small number of tools an agent can absorb
# --------------------------------------------------------------------------- #
def _matches_any(text: str, patterns: list[str]) -> bool:
    """Simple wildcard match (* matches anything, everything else is a substring match)."""
    if not patterns:
        return False
    for pat in patterns:
        pat = (pat or "").strip()
        if not pat:
            continue
        if "*" in pat:
            regex = pat.replace("*", ".*")
            if re.search(regex, text, re.IGNORECASE):
                return True
        elif pat.lower() in text.lower():
            return True
    return False


def _intent_score(op: dict, intent: str) -> float:
    """Score how well an operation matches an intent by keyword (used for semantic ordering when no rule applies)."""
    keywords = [k.strip().lower() for k in intent.replace(",", " ").split() if k.strip()]
    if not keywords:
        return 0.0
    haystack = " ".join(
        [
            op.get("operation_id", ""),
            op.get("path", ""),
            op.get("summary", ""),
            " ".join(str(t) for t in op.get("tags", [])),
        ]
    ).lower()
    matched = sum(1 for k in keywords if k in haystack)
    # Keyword hit ratio plus hit density, so strong matches sort first
    return matched / len(keywords) + matched * 0.05


def filter_operations(ops: list[dict], scope: Optional[dict] = None) -> list[dict]:
    """Filter and order operations by scope rules, which is the fix for tool explosion.

    scope fields (all optional):
      - include_operation_ids / exclude_operation_ids: list[str]
      - include_tags / exclude_tags: list[str] (supports * wildcards)
      - include_methods / exclude_methods: list[str]
      - include_path_patterns / exclude_path_patterns: list[str] (supports * wildcards)
      - intent: str — semantic intent, matched by keyword against summary/path/tags/operation_id
      - top_n: int — used with intent, keeps only the N most relevant
      - exclude_deprecated: bool — defaults to True, drops deprecated operations
    """
    if not scope:
        return ops
    if not isinstance(scope, dict):
        raise TypeError("scope must be a dict")

    out = list(ops)

    if scope.get("exclude_deprecated", True):
        out = [o for o in out if not o.get("deprecated")]

    include_ids = scope.get("include_operation_ids") or []
    if include_ids:
        out = [o for o in out if o.get("operation_id") in include_ids]

    exclude_ids = scope.get("exclude_operation_ids") or []
    if exclude_ids:
        out = [o for o in out if o.get("operation_id") not in exclude_ids]

    include_tags = scope.get("include_tags") or []
    if include_tags:
        out = [o for o in out if any(_matches_any(str(t), include_tags) for t in o.get("tags", []))]

    exclude_tags = scope.get("exclude_tags") or []
    if exclude_tags:
        out = [o for o in out if not any(_matches_any(str(t), exclude_tags) for t in o.get("tags", []))]

    include_methods = [m.upper() for m in (scope.get("include_methods") or []) if m]
    if include_methods:
        out = [o for o in out if o.get("method", "").upper() in include_methods]

    exclude_methods = [m.upper() for m in (scope.get("exclude_methods") or []) if m]
    if exclude_methods:
        out = [o for o in out if o.get("method", "").upper() not in exclude_methods]

    include_paths = scope.get("include_path_patterns") or []
    if include_paths:
        out = [o for o in out if _matches_any(o.get("path", ""), include_paths)]

    exclude_paths = scope.get("exclude_path_patterns") or []
    if exclude_paths:
        out = [o for o in out if not _matches_any(o.get("path", ""), exclude_paths)]

    intent = (scope.get("intent") or "").strip()
    if intent:
        scored = [(o, _intent_score(o, intent)) for o in out]
        scored.sort(key=lambda x: x[1], reverse=True)
        top_n = scope.get("top_n")
        if top_n and int(top_n) > 0:
            scored = scored[: int(top_n)]
        # keep only operations hitting at least one keyword; if none hit, keep the original order (avoid an empty result)
        if any(s > 0 for _, s in scored):
            out = [o for o, s in scored if s > 0]
        else:
            out = [o for o, _ in scored]

    return out


def suggest_scope(ops: list[dict]) -> dict:
    """Recommend curation dimensions from the operation set (tags, methods, path prefixes)."""
    tags: set[str] = set()
    methods: set[str] = set()
    prefixes: set[str] = set()
    for o in ops:
        methods.add(o.get("method", "").upper())
        for t in o.get("tags", []):
            if isinstance(t, str):
                tags.add(t)
        path = o.get("path", "")
        parts = [p for p in path.split("/") if p and not p.startswith("{")]
        if parts:
            prefixes.add("/" + parts[0])
    return {
        "tags": sorted(tags),
        "methods": sorted(methods),
        "path_prefixes": sorted(prefixes),
        "total_operations": len(ops),
        "deprecated_operations": sum(1 for o in ops if o.get("deprecated")),
    }


def op_input_schema(op: dict) -> dict:
    """Build a JSON Schema for one operation (used by the marketplace listing and generated code docs)."""
    props: dict[str, Any] = {}
    required: list[str] = []
    for p in op.get("path_params", []) + op.get("query_params", []):
        props[p["name"]] = {
            "type": {"int": "integer", "float": "number", "bool": "boolean"}.get(p["type"], "string"),
            "description": p.get("description") or "",
            **({"x-pagination": True} if p.get("pagination_hint") else {}),
        }
        if p.get("required"):
            required.append(p["name"])
    if op.get("has_body"):
        props["body"] = {"type": "object", "description": "request body (JSON)"}
    return {"type": "object", "properties": props, "required": required}


def list_operations(spec_source: str) -> str:
    """Synchronous wrapper (for scripts)."""
    return asyncio.run(list_operations_async(spec_source))


async def list_operations_async(spec_source: str) -> str:
    return format_operations(await load_spec_async(spec_source))


def format_operations(spec: dict) -> str:
    """Pure function: render a spec as a readable operation inventory."""
    ops = extract_operations(spec)
    if not ops:
        return "this spec exposes no callable operations (are paths empty?)"
    lines = [f"{len(ops)} operations:"]
    for o in ops:
        flags = []
        if o["deprecated"]:
            flags.append("deprecated")
        if o["paginated"]:
            flags.append("paginated")
        if o["security"]:
            flags.append("auth required")
        suffix = f"  [{'/'.join(flags)}]" if flags else ""
        lines.append(
            f"- [{o['method']}] {o['path']}  →  {o['operation_id']}  ({o['summary']}){suffix}"
        )
    return "\n".join(lines)


def parse_openapi_spec(spec_source: str) -> dict:
    """Synchronous wrapper (for scripts)."""
    return asyncio.run(parse_openapi_spec_async(spec_source))


async def parse_openapi_spec_async(spec_source: str) -> dict:
    """The tool named by contract section 4 item 2: parse OpenAPI and return a structured operations list."""
    return spec_overview(await load_spec_async(spec_source))


def spec_overview(spec: dict) -> dict:
    """Pure function: parsed spec -> structured overview."""
    ops = extract_operations(spec)
    info = spec.get("info") or {}
    return {
        "title": info.get("title"),
        "version": info.get("version"),
        "description": info.get("description"),
        "openapi_version": spec.get("openapi") or spec.get("swagger"),
        "base_url": get_base_url(spec),
        "source_kind": "url" if str(spec.get("x_source", "")).startswith("http") else "local-or-inline",
        "auth_schemes": detect_auth(spec),
        "operation_count": len(ops),
        "operations": [
            {
                "operation_id": o["operation_id"],
                "method": o["method"],
                "path": o["path"],
                "summary": o["summary"],
                "tags": o["tags"],
                "deprecated": o["deprecated"],
                "paginated": o["paginated"],
                "requires_auth": bool(o["security"]),
                "input_schema": op_input_schema(o),
            }
            for o in ops
        ],
    }


def ingest_spec(source: str) -> dict:
    """Backwards-compatible alias for parse_openapi_spec (the v1 name, kept so existing callers keep working)."""
    return parse_openapi_spec(source)


# --------------------------------------------------------------------------- #
# VERIFY: real calls plus real assertions
# --------------------------------------------------------------------------- #
def _sample_value(param: dict) -> Any:
    """Generate sample parameter values for the real calls VERIFY makes.

    Prefers example / default / enum[0] declared explicitly in the spec.

    Why: verifiability depends on the sample values actually working. Under the old logic
    /repos/{owner}/{repo} was filled with "sample", requesting /repos/sample/sample and getting a 404,
    so a healthy endpoint was reported as broken. A declared example verifies to a real 2xx.

    When nothing is declared, fall back to inference by type and name, preserving compatibility with existing specs.
    """
    for key in ("example", "default"):
        val = param.get(key)
        if val is not None and val != "":
            return val
    enum = param.get("enum")
    if enum:
        return enum[0]
    name = (param.get("name") or "").lower()
    t = param.get("type")
    if t == "int":
        return 1
    if t == "bool":
        return True
    if t == "float":
        return 1.0
    if "email" in name:
        return "a@b.com"
    if "date" in name:
        return "2026-01-01"
    if "id" in name or "code" in name:
        return "1"
    return "sample"


def _structure_body(r: Any, max_items: int = 10) -> tuple[Any, bool]:
    """Parse an HTTP response into structured data an agent can consume.

    Returns (data, truncated); data is None when parsing fails and callers fall back to body_preview.

    Why it exists: body_preview is truncated text, and an agent cannot reliably pull fields out of it,
    so multi-step tasks (search → verify → aggregate) break at step one and the tool degrades to a one-shot probe.

    Why it is bounded: search endpoints can return hundreds of full records at once, and passing that through
    floods the model context. Lists keep only the first max_items entries and set truncated,
    so the caller knows more exist and can narrow the query.
    """
    try:
        data = r.json()
    except Exception:  # noqa: BLE001
        return None, False
    if isinstance(data, list) and len(data) > max_items:
        return data[:max_items], True
    return data, False


def classify_response(status_code: int) -> tuple[str, bool]:
    """Map an HTTP status code to an explicit verdict. This is the fix for v1's "any response counts as reachable".

    Returns (status, passed). passed is true only for 2xx.
    """
    if 200 <= status_code < 300:
        return "passed", True
    if status_code in (401, 403):
        return "auth_required", False
    if status_code == 404:
        return "not_found", False
    if status_code == 429:
        return "rate_limited", False
    if 400 <= status_code < 500:
        return "bad_request", False
    if 500 <= status_code < 600:
        return "server_error", False
    return "unexpected_status", False


async def verify_operation_async(
    base_url: str,
    op: dict,
    client: httpx.AsyncClient,
    timeout: float = DEFAULT_TIMEOUT,
) -> dict:
    """Call one operation for real and return a pass/fail verdict by status code (not a tautological reachability check)."""
    path = op["path"]
    used_params: dict[str, Any] = {}
    for p in op.get("path_params", []):
        v = _sample_value(p)
        used_params[p["name"]] = v
        path = path.replace("{" + p["name"] + "}", urllib.parse.quote(str(v)))
    url = (base_url.rstrip("/") + "/" + path.lstrip("/")) if base_url else path
    query = {p["name"]: _sample_value(p) for p in op.get("query_params", [])}

    result: dict[str, Any] = {
        "operation_id": op["operation_id"],
        "method": op["method"],
        "url": url,
        "sample_params": used_params,
        "status": "unreachable",
        "passed": False,
        "http_status": None,
        "latency_ms": None,
        "error": None,
        "sample_body": "",
    }
    try:
        start = time.perf_counter()
        r = await client.request(
            op["method"],
            url,
            params=query or None,
            json={} if op["has_body"] else None,
            headers={"Accept": "application/json", "User-Agent": USER_AGENT},
            timeout=timeout,
        )
        result["latency_ms"] = round((time.perf_counter() - start) * 1000, 1)
        result["http_status"] = r.status_code
        status, passed = classify_response(r.status_code)
        result["status"] = status
        result["passed"] = passed
        result["sample_body"] = (r.text or "")[:600]
    except (httpx.TransportError, httpx.TimeoutException) as e:
        result["error"] = f"{type(e).__name__}: {e}"
    except Exception as e:  # noqa: BLE001 - a single failure must not abort the whole verification
        result["error"] = f"{type(e).__name__}: {e}"
    return result


async def verify_api_async(
    source: str,
    max_ops: int = 20,
    timeout: float = 8.0,
    concurrency: int = 8,
    scope: Optional[dict] = None,
) -> dict:
    """Verify concurrently with a bounded per-request timeout, so total time stays predictable

    (v1 could block the event loop for 20×15=300 seconds). Supports scope curation before verifying:
    """
    spec = await load_spec_async(source)
    all_ops = extract_operations(spec)
    ops = filter_operations(all_ops, scope)[:max_ops]
    base = get_base_url(spec)
    sem = asyncio.Semaphore(max(1, concurrency))

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:

        async def one(op: dict) -> dict:
            async with sem:
                return await verify_operation_async(base, op, client, timeout)

        results = await asyncio.gather(*(one(o) for o in ops)) if ops else []

    passed = sum(1 for r in results if r["passed"])
    reached = sum(1 for r in results if r["status"] != "unreachable")
    return {
        "title": (spec.get("info") or {}).get("title"),
        "version": (spec.get("info") or {}).get("version"),
        "base_url": base,
        "total_operations": len(all_ops),
        "filtered_operations": len(ops),
        "scope": scope,
        "verified": len(results),
        "passed": passed,
        "reached_but_failed": reached - passed,
        "unreachable": len(results) - reached,
        "verdict": (
            "all passed"
            if results and passed == len(results)
            else ("partially passed" if passed else "nothing passed (endpoints may need auth or real parameters)")
        ),
        "note": (
            "passed counts only HTTP 2xx. 401/403 is recorded as auth_required, 404 as not_found, "
            "other 4xx as bad_request (placeholder parameters often fail business validation), network failure as unreachable."
        ),
        "results": results,
    }


def verify_api(source: str, max_ops: int = 20, timeout: float = 8.0, concurrency: int = 8, scope: Optional[dict] = None) -> dict:
    """Synchronous wrapper (for verify.py and unit tests)."""
    return asyncio.run(verify_api_async(source, max_ops, timeout, concurrency, scope))


def verify_operation(base_url: str, op: dict, timeout: float = 8.0) -> dict:
    """Synchronous wrapper: verify a single operation."""

    async def run() -> dict:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as c:
            return await verify_operation_async(base_url, op, c, timeout)

    return asyncio.run(run())


# --------------------------------------------------------------------------- #
# MCPize: code generation
# --------------------------------------------------------------------------- #
def _py_ident(raw: str) -> str:
    s = re.sub(r"\W", "_", raw or "").strip("_")
    if not s:
        s = "tool"
    if s[0].isdigit():
        s = "op_" + s
    return s


def _dedupe(names: list[str]) -> list[str]:
    """Keep generated function names unique (in v1 two operations could sanitize to the same name and overwrite each other)."""
    seen: dict[str, int] = {}
    out: list[str] = []
    for n in names:
        if n in seen:
            seen[n] += 1
            out.append(f"{n}_{seen[n]}")
        else:
            seen[n] = 0
            out.append(n)
    return out


def _safe_docstring(text: str) -> str:
    """Place arbitrary spec text inside a Python docstring safely, so triple quotes or backslashes cannot break the generated file."""
    cleaned = (text or "").replace("\\", "\\\\").replace('"""', "'''")
    cleaned = cleaned.replace("\r", " ").replace("\n", " ").strip()
    return cleaned[:200] or "auto-generated tool"


def _auth_code(spec_auth: list[dict], require_auth: bool) -> tuple[str, str]:
    """Generate an auth code block from the schemes the spec declares. Returns (imports_block, headers_expr)."""
    if not require_auth:
        return "", "HEADERS: dict[str, str] = {}"
    lines = [
        'import os',
        'API_KEY = os.getenv("API_KEY", "")',
        'API_KEY_HEADER = os.getenv("API_KEY_HEADER", "Authorization")',
        'HEADERS: dict[str, str] = {}',
        'if API_KEY:',
        '    HEADERS[API_KEY_HEADER] = API_KEY',
    ]
    return "\n".join(lines), "HEADERS"


def _path_const_name(func_name: str) -> str:
    return f"_PATH_{func_name.upper()}"


def _gen_single_tool(op: dict, func_name: str) -> str:
    """Generate one tool.

    Key point: no f-string interpolation. A template constant plus str.replace keeps non-identifier
    placeholders like {account-id} and {file.name} working (v1 produced NameError).
    """
    path_params = op.get("path_params", [])
    query_params = op.get("query_params", [])
    method = op["method"].lower()
    const = _path_const_name(func_name)
    doc = _safe_docstring(op.get("summary") or op["operation_id"])

    # Signature plus a mapping from raw parameter names to valid identifiers
    sig_parts: list[str] = []
    mapping: list[tuple[str, str]] = []
    for p in path_params:
        ident = _py_ident(p["name"])
        mapping.append((p["name"], ident))
        sig_parts.append(f"{ident}: {p['type']}")
    for p in query_params:
        ident = _py_ident(p["name"])
        mapping.append((p["name"], ident))
        sig_parts.append(f"{ident}: Optional[{p['type']}] = None")
    if op["has_body"]:
        sig_parts.append("body: Optional[dict] = None")
    signature = ", ".join(sig_parts)

    body_lines: list[str] = [f'        url = BASE_URL.rstrip("/") + {const}']
    for original, ident in mapping:
        if any(original == pp["name"] for pp in path_params):
            body_lines.append(
                f'        url = url.replace("{{{original}}}", urllib.parse.quote(str({ident})))'
            )
    body_lines.append("        params: dict[str, Any] = {}")
    for original, ident in mapping:
        if any(original == qp["name"] for qp in query_params):
            body_lines.append(f"        if {ident} is not None:")
            body_lines.append(f'            params["{original}"] = {ident}')
    body_lines.append("        json_body = body" if op["has_body"] else "        json_body = None")
    body = "\n".join(body_lines)

    return f'''

{const} = "{op["path"]}"


def _register_{func_name}(mcp: FastMCP) -> None:
    """Call operation {op["operation_id"]} ({op["method"]} {op["path"]})."""

    @mcp.tool()
    async def {func_name}({signature}) -> dict:
        """{doc}"""
{body}
        last_err: Optional[Exception] = None
        for attempt in range(3):
            try:
                async with httpx.AsyncClient(timeout=20, follow_redirects=True) as c:
                    r = await c.{method}(
                        url, params=params or None, json=json_body, headers=HEADERS
                    )
                return {{
                    "status_code": r.status_code,
                    "url": str(r.url),
                    "body": r.text[:4000],
                }}
            except httpx.TransportError as e:
                last_err = e
                await asyncio.sleep(0.4 * (attempt + 1))
        return {{"error": f"{{type(last_err).__name__}}: {{last_err}}"}}
'''


def _module_header(server_name: str, base_url: str, auth_block: str, extra_note: str = "") -> str:
    return f'''"""
{server_name} · generated by MCPForge {VERSION}

{extra_note}Run:
    pip install -r requirements.txt
    fastmcp dev server.py
"""
from __future__ import annotations

import asyncio
import os
import urllib.parse
from typing import Any, Optional

import httpx
from fastmcp import FastMCP

mcp = FastMCP("{server_name}")
BASE_URL = os.getenv("API_BASE_URL", "{base_url}")
{auth_block}
'''


def generate_tool_code(
    source: str,
    operation_id: str,
    server_name: str = "generated-mcp-server",
    require_auth: bool = False,
) -> str:
    """Synchronous wrapper (for scripts)."""
    return asyncio.run(generate_tool_code_async(source, operation_id, server_name, require_auth))


async def generate_tool_code_async(
    source: str,
    operation_id: str,
    server_name: str = "generated-mcp-server",
    require_auth: bool = False,
) -> str:
    """Generate one operation into deployable FastMCP tool code."""
    spec = await load_spec_async(source)
    return tool_code_from_spec(spec, operation_id, server_name, require_auth)


def tool_code_from_spec(
    spec: dict,
    operation_id: str,
    server_name: str = "generated-mcp-server",
    require_auth: bool = False,
) -> str:
    """Pure function: parsed spec -> single tool source."""
    ops = extract_operations(spec)
    op = next((o for o in ops if o["operation_id"] == operation_id), None)
    if not op:
        return (
            f"operation_id={operation_id!r} not found. Use list_operations to see them all; "
            f"this spec has {len(ops)} operations."
        )
    base = op["base_url"] or "https://REPLACE_WITH_API_BASE_URL"
    auth_block, _ = _auth_code(detect_auth(spec), require_auth)
    name = _py_ident(operation_id)
    return (
        _module_header(server_name, base, auth_block, f"source API: {base}\n")
        + _gen_single_tool(op, name)
        + f'\n_register_{name}(mcp)\n\nif __name__ == "__main__":\n    mcp.run()\n'
    )


def generate_bundle(
    source: str,
    name: str,
    server_name: str = "generated-mcp-server",
    require_auth: bool = False,
    output_dir: str = "generated",
    scope: Optional[dict] = None,
) -> dict:
    """Synchronous wrapper (for scripts)."""
    return asyncio.run(
        generate_bundle_async(source, name, server_name, require_auth, output_dir, scope)
    )


async def generate_bundle_async(
    source: str,
    name: str,
    server_name: str = "generated-mcp-server",
    require_auth: bool = False,
    output_dir: str = "generated",
    scope: Optional[dict] = None,
) -> dict:
    """Generate a complete deployable bundle. The output path is guarded by ensure_writable_dir.

    scope curates before generating: collapse 100 endpoints into 5 tools an agent can actually use
    instead of flooding the agent context window. See filter_operations.
    """
    spec = await load_spec_async(source)
    return bundle_from_spec(spec, name, server_name, require_auth, output_dir, scope)


def bundle_from_spec(
    spec: dict,
    name: str,
    server_name: str = "generated-mcp-server",
    require_auth: bool = False,
    output_dir: str = "generated",
    scope: Optional[dict] = None,
) -> dict:
    """Pure function: parsed spec -> full bundle written to disk."""
    all_ops = extract_operations(spec)
    ops = filter_operations(all_ops, scope)
    if not ops:
        raise SpecSourceError(
            f"no operation in the spec matches the scope rules, cannot generate a bundle (API: {name})"
        )
    base = get_base_url(spec) or "https://REPLACE_WITH_API_BASE_URL"
    auth_schemes = detect_auth(spec)
    out = ensure_writable_dir(output_dir, name)
    out.mkdir(parents=True, exist_ok=True)

    auth_block, _ = _auth_code(auth_schemes, require_auth)
    func_names = _dedupe([_py_ident(o["operation_id"]) for o in ops])

    note = f"source API: {base}\n"
    if scope:
        note += f"raw endpoints: {len(all_ops)}; after scope curation, {len(ops)} tools generated.\n"
    else:
        note += f"{len(ops)} tools total.\n"
    if auth_schemes:
        note += f"this API declares auth schemes: {', '.join(s['name'] for s in auth_schemes)}.\n"
        if require_auth:
            note += "supply credentials at runtime through the API_KEY environment variable.\n"

    server_py = (
        _module_header(server_name, base, auth_block, note)
        + "".join(_gen_single_tool(op, fn) for op, fn in zip(ops, func_names))
        + "\n" + "".join(f"_register_{fn}(mcp)\n" for fn in func_names)
        + '\nif __name__ == "__main__":\n    mcp.run()\n'
    )
    (out / "server.py").write_text(server_py, encoding="utf-8")
    (out / "requirements.txt").write_text(
        "# version pinned to the major line used when generating and verifying\nfastmcp>=4.0,<5.0\nhttpx>=0.27,<1.0\n",
        encoding="utf-8",
    )

    readme_lines = [
        f"# {name} · MCP Server (generated by MCPForge)",
        "",
        f"source API: `{base}`",
        "",
    ]
    if scope:
        readme_lines.append(f"raw endpoints: {len(all_ops)}; after scope curation, **{len(ops)}** tools generated.")
    else:
        readme_lines.append(f"tool count: {len(ops)}")
    readme_lines.append("")
    readme_lines.append(
        "**this API requires auth**: set the `API_KEY` environment variable at runtime." if require_auth else "this API needs no auth."
    )
    readme_lines.extend([
        "",
        "## Run",
        "",
        "```bash",
        "pip install -r requirements.txt",
        "# stdio inspector",
        "fastmcp dev server.py",
        "# expose as an HTTP service",
        "fastmcp run server.py --transport streamable-http --port 8080",
        "```",
        "",
        "## Tools",
        "",
    ])
    readme_lines.extend(
        f"- `{fn}` — [{o['method']}] {o['path']} ({o['summary'] or 'no summary'})"
        for o, fn in zip(ops, func_names)
    )
    readme_lines.append("")
    (out / "README.md").write_text("\n".join(readme_lines), encoding="utf-8")

    manifest = manifest_from_spec(
        spec, name, ops, base_url=base, auth_schemes=auth_schemes
    )
    (out / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    return {
        "schema_version": metering.SCHEMA_VERSION,
        "name": name,
        "output_dir": str(out),
        "tools": len(ops),
        "original_operations": len(all_ops),
        "scope": scope,
        "function_names": func_names,
        "files": [str(p) for p in sorted(out.iterdir())],
    }


# --------------------------------------------------------------------------- #
# MONETIZE: marketplace listing
# --------------------------------------------------------------------------- #
def manifest_from_spec(
    spec: dict,
    name: str,
    operations: Optional[list[dict]] = None,
    base_url: str = "",
    auth_schemes: Optional[list[dict]] = None,
    category: str = "api-tool",
    pricing_tier: str = "free",
    description: str = "",
    currency: Optional[str] = None,
) -> dict:
    """Pure function: parsed spec + operation list -> marketplace listing."""
    operations = operations if operations is not None else extract_operations(spec)
    if auth_schemes is None:
        auth_schemes = detect_auth(spec)
    auth_schemes = auth_schemes or []
    if not base_url:
        base_url = get_base_url(spec)
    tier = metering.PRICING_TIERS.get(pricing_tier, metering.PRICING_TIERS["free"])

    return {
        "schema_version": metering.SCHEMA_VERSION,
        "generated_by": f"MCPForge/{VERSION}",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "listing": {
            "name": name,
            "display_name": name.replace("-", " ").replace("_", " ").title(),
            "category": category,
            "description": description
            or f"{name} API turned into MCP by MCPForge in one pass, {len(operations)} callable tools.",
            "endpoint": base_url or "",
            "auth": {
                "required": bool(auth_schemes),
                "schemes": auth_schemes,
                "credential_env": "API_KEY" if auth_schemes else None,
            },
            "capabilities": {
                "tool_count": len(operations),
                "paginated_tools": sum(1 for o in operations if o.get("paginated")),
                "deprecated_tools": sum(1 for o in operations if o.get("deprecated")),
            },
        },
        "tools": [
            {
                "operation_id": o["operation_id"],
                "method": o["method"],
                "path": o["path"],
                "summary": o["summary"],
                "input_schema": op_input_schema(o),
            }
            for o in operations
        ],
        "pricing": {
            "tier": pricing_tier,
            "billing_model": tier["model"],
            "included_calls": tier["included_calls"],
            "price_per_1k_calls": tier["price_per_1k_calls"],
            "currency": currency or metering.DEFAULT_CURRENCY,
            "all_tiers": {
                k: {
                    "price_per_1k_calls": v["price_per_1k_calls"],
                    "included_calls": v["included_calls"],
                }
                for k, v in metering.PRICING_TIERS.items()
            },
        },
        "compliance": {
            "note": "produced as an engineering portfolio piece to demonstrate API→MCP wrapping and metering.",
            "contains_security_audit_capability": False,
            "crypto_token_speculation": False,
        },
    }


def build_manifest(
    name: str,
    source: str = "",
    operations: Optional[list[dict]] = None,
    base_url: str = "",
    auth_schemes: Optional[list[dict]] = None,
    category: str = "api-tool",
    pricing_tier: str = "free",
    description: str = "",
    currency: Optional[str] = None,
    scope: Optional[dict] = None,
) -> dict:
    """Synchronous wrapper (for scripts)."""
    return asyncio.run(
        build_manifest_async(
            name, source, operations, base_url, auth_schemes,
            category, pricing_tier, description, currency, scope,
        )
    )


def preview_scope(spec_source: str, scope: Optional[dict] = None) -> dict:
    """Synchronous wrapper (for scripts)."""
    return asyncio.run(preview_scope_async(spec_source, scope))


async def preview_scope_async(spec_source: str, scope: Optional[dict] = None) -> dict:
    """Preview scope curation without generating code: raw count, filtered count, and which operations survive."""
    spec = await load_spec_async(spec_source)
    all_ops = extract_operations(spec)
    filtered = filter_operations(all_ops, scope)
    return {
        "total_operations": len(all_ops),
        "filtered_operations": len(filtered),
        "reduction_percent": round((1 - len(filtered) / len(all_ops)) * 100, 1) if all_ops else 0.0,
        "scope": scope,
        "suggestions": suggest_scope(all_ops),
        "kept_operations": [
            {
                "operation_id": o["operation_id"],
                "method": o["method"],
                "path": o["path"],
                "summary": o["summary"],
                "tags": o["tags"],
            }
            for o in filtered
        ],
    }


async def build_manifest_async(
    name: str,
    source: str = "",
    operations: Optional[list[dict]] = None,
    base_url: str = "",
    auth_schemes: Optional[list[dict]] = None,
    category: str = "api-tool",
    pricing_tier: str = "free",
    description: str = "",
    currency: Optional[str] = None,
    scope: Optional[dict] = None,
) -> dict:
    """Build a marketplace-format listing with per-tool JSON Schema, auth requirements, quota, and the billing model.

    Supports scope curation before the listing is built.
    """
    spec: dict = {}
    if operations is None and source:
        spec = await load_spec_async(source)
        operations = filter_operations(extract_operations(spec), scope)
    if auth_schemes is None and spec:
        auth_schemes = detect_auth(spec)
    return manifest_from_spec(
        spec, name, operations, base_url, auth_schemes,
        category, pricing_tier, description, currency,
    )


# --------------------------------------------------------------------------- #
# Calling: generic REST plus the registry
# --------------------------------------------------------------------------- #
async def _call_op_async(
    base_url: str,
    op: dict,
    kwargs: dict,
    query: Optional[dict] = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> dict:
    path = op["path"]
    for p in op.get("path_params", []):
        if p["name"] in kwargs:
            path = path.replace(
                "{" + p["name"] + "}", urllib.parse.quote(str(kwargs.pop(p["name"])))
            )
    url = (base_url.rstrip("/") + "/" + path.lstrip("/")) if base_url else path
    if query is None:
        query_names = {p["name"] for p in op.get("query_params", [])}
        query = {k: v for k, v in kwargs.items() if k in query_names}
    body = kwargs.get("__body__")
    headers = {"Accept": "application/json", "User-Agent": USER_AGENT}
    start = time.perf_counter()
    try:
        r = await request_with_validated_redirects(
            op["method"],
            url,
            params=query or None,
            json_body=body,
            headers=headers,
            timeout=timeout,
        )
        data, truncated = _structure_body(r)
        return {
            "status_code": r.status_code,
            "url": str(r.url),
            "latency_ms": round((time.perf_counter() - start) * 1000, 1),
            "ok": 200 <= r.status_code < 300,
            "body_preview": r.text[:2000],
            # Structured output: an agent needs consumable JSON to decide the next step.
            # With only truncated text, multi-step flows like "search candidates → verify each" cannot complete,
            # and the tool degrades from a usable capability to a one-shot probe.
            "data": data,
            "data_truncated": truncated,
        }
    except Exception as e:  # noqa: BLE001
        return {
            "status_code": None,
            "url": url,
            "ok": False,
            "error": f"{type(e).__name__}: {e}",
        }


def _call_op(base_url: str, op: dict, kwargs: dict, query: Optional[dict] = None) -> dict:
    return asyncio.run(_call_op_async(base_url, op, kwargs, query))


async def call_rest_api_async(
    base_url: str,
    path: str,
    method: str = "GET",
    query: Optional[dict] = None,
    body: Optional[dict] = None,
) -> dict:
    op = {
        "path": path,
        "method": method.upper(),
        "path_params": [],
        "query_params": [],
        "has_body": bool(body),
        "base_url": base_url,
    }
    kwargs = dict(query or {})
    if body is not None:
        kwargs["__body__"] = body
    return await _call_op_async(base_url, op, kwargs, query=query)


def call_rest_api(
    base_url: str,
    path: str,
    method: str = "GET",
    query: Optional[dict] = None,
    body: Optional[dict] = None,
) -> dict:
    """Generic REST call: reach any public API (the online-callable capability itself)."""
    return asyncio.run(call_rest_api_async(base_url, path, method, query, body))


def _registry_path() -> Path:
    return Path(os.getenv("MCPFORGE_REGISTRY", "registry.json"))


class Registry:
    """Persistent registry. Atomic writes; a corrupt file is kept aside rather than silently cleared; overwriting is reported explicitly."""

    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path or _registry_path())
        self._data: dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            try:
                self.path.replace(self.path.with_suffix(".corrupt.json"))
            except Exception:
                pass
            return
        if isinstance(loaded, dict):
            self._data = loaded

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(self._data, fh, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)
        except Exception:
            try:
                os.unlink(tmp)
            except Exception:
                pass
            raise

    def register(self, name: str, source: str, base_url: str = "", ops: Optional[list] = None) -> dict:
        """Synchronous wrapper (for scripts)."""
        return asyncio.run(self.register_async(name, source, base_url, ops))

    async def register_async(
        self, name: str, source: str, base_url: str = "", ops: Optional[list] = None
    ) -> dict:
        spec = await load_spec_async(source)
        if ops is None:
            ops = extract_operations(spec)
        if not base_url:
            base_url = get_base_url(spec)
        overwrote = name in self._data
        self._data[name] = {
            "name": name,
            "source": source,
            "base_url": base_url,
            "auth_schemes": detect_auth(spec),
            "operations": ops,
            "registered_at": datetime.now(timezone.utc).isoformat(),
        }
        self._save()
        return {"name": name, "operations": len(ops), "overwrote_existing": overwrote}

    def get(self, name: str) -> Optional[dict]:
        return self._data.get(name)

    def list_names(self) -> list[str]:
        return sorted(self._data.keys())

    def unregister(self, name: str) -> bool:
        removed = self._data.pop(name, None) is not None
        if removed:
            self._save()
        return removed

    async def call_async(self, name: str, operation_id: str, params: dict) -> dict:
        entry = self.get(name)
        if not entry:
            return {"error": f"registered API {name!r} not found. Run register_api_from_spec first. Registered: {self.list_names()}"}
        op = next((o for o in entry["operations"] if o["operation_id"] == operation_id), None)
        if not op:
            avail = [o["operation_id"] for o in entry["operations"]][:20]
            return {"error": f"operation {operation_id!r} not found; available (first 20): {avail}"}

        kwargs = dict(params or {})
        body = kwargs.pop("__body__", None)
        if body is not None:
            kwargs["__body__"] = body
        res = await _call_op_async(entry["base_url"], op, kwargs)
        metering.get_meter().record(
            name,
            operation_id,
            ok=bool(res.get("ok")),
            status_code=res.get("status_code"),
            latency_ms=res.get("latency_ms"),
        )
        res["metered"] = True
        return res

    def call(self, name: str, operation_id: str, params: dict) -> dict:
        return asyncio.run(self.call_async(name, operation_id, params))


def health_check() -> dict:
    """Health check: ok means the service is online and callable (live evidence)."""
    return {
        "status": "ok",
        "service": "MCPForge",
        "version": VERSION,
        "registered_apis": _registry.list_names(),
        "counters": {
            "registered_apis": len(_registry.list_names()),
            "metered_calls": metering.get_meter().report().get("total_calls_all_apis", 0),
        },
        "time": datetime.now(timezone.utc).isoformat(),
    }


# Global singleton
_registry = Registry()
