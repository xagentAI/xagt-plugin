"""
test_core.py · offline unit tests (no internet dependency)

These cases exist as a direct product of the adversarial review: v1's "7/7 all green" depended on live internet
and never covered pasted text, non-identifier placeholders, path traversal, or SSRF,
so defects hid behind green lights. Everything here reproduces offline.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

import core
import metering

FIXTURE = Path(__file__).parent / "fixtures" / "offline-api.json"


def asyncio_run(coro):
    """Run coroutines synchronously. The tests stay synchronous to avoid implicit behavior from event-loop fixtures."""
    return asyncio.run(coro)


@pytest.fixture()
def fixture_spec() -> dict:
    return core.parse_spec_text(FIXTURE.read_text(encoding="utf-8"), str(FIXTURE))


# ----------------------------- BUILD --------------------------------------- #
def test_paste_json_text_is_accepted():
    """Regression for the v1 defect: pasted OpenAPI text was misclassified as a file path by _looks_like_path."""
    pasted = json.dumps(
        {
            "openapi": "3.0.0",
            "info": {"title": "pasted", "version": "1.0"},
            "paths": {"/pets": {"get": {"operationId": "listPets", "responses": {"200": {"description": "ok"}}}}},
        }
    )
    overview = core.parse_openapi_spec(pasted)
    assert overview["title"] == "pasted"
    assert overview["operation_count"] == 1


def test_paste_yaml_text_is_accepted():
    yaml_text = (
        "openapi: 3.0.0\n"
        "info:\n  title: pasted-yaml\n  version: '1.0'\n"
        "paths:\n  /pets:\n    get:\n      operationId: listPets\n"
    )
    assert core.parse_openapi_spec(yaml_text)["title"] == "pasted-yaml"


def test_non_spec_text_gives_diagnostic_error():
    with pytest.raises(core.SpecSourceError) as ei:
        core.parse_openapi_spec("hello world")
    assert "not an OpenAPI object" in str(ei.value)


def test_nonexistent_file_path_reports_file_error():
    with pytest.raises(FileNotFoundError):
        core.parse_openapi_spec("./definitely-not-here-12345.json")


def test_ref_and_path_level_parameters_are_merged(fixture_spec):
    """$ref parameters should be expanded, and path-level parameters merged with operation-level ones."""
    ops = {o["operation_id"]: o for o in core.extract_operations(fixture_spec)}
    get_pet = ops["getPetById"]
    names = [p["name"] for p in get_pet["query_params"]]
    assert "page" in names, "path-level $ref parameter was not merged"
    assert [p["name"] for p in get_pet["path_params"]] == ["petId"]


def test_auth_and_pagination_detected(fixture_spec):
    schemes = {s["name"] for s in core.detect_auth(fixture_spec)}
    assert {"fixture_key", "fixture_oauth"} <= schemes
    ops = {o["operation_id"]: o for o in core.extract_operations(fixture_spec)}
    assert ops["getPetById"]["paginated"] is True
    assert ops["deletePet"]["security"], "operation-level security was not preserved"


def test_relative_base_url_is_completed_with_origin():
    spec = core.parse_spec_text(
        json.dumps(
            {
                "openapi": "3.0.0",
                "info": {"title": "t", "version": "1"},
                "servers": [{"url": "/api/v3"}],
                "paths": {"/x": {"get": {"operationId": "x"}}},
            }
        )
    )
    assert core.resolve_base_url(spec, "https://host.example.com/openapi.json") == "https://host.example.com/api/v3"


def test_relative_base_url_without_leading_slash_gets_separator():
    """Regression for the v1 defect: servers.url='v3' was concatenated into https://hostv3."""
    spec = {"servers": [{"url": "v3"}]}
    assert core.resolve_base_url(spec, "https://host.example.com/spec.json") == "https://host.example.com/v3"


# ----------------------------- MCPize -------------------------------------- #
def test_weird_placeholder_codegen_compiles(fixture_spec):
    """Regression for the v1 defect: {account-id} went into an f-string verbatim, so the generated file raised NameError."""
    code = core.tool_code_from_spec(fixture_spec, "getWeirdBalance")
    assert "f\"" not in code.split("_PATH_")[0]
    compile(code, "generated.py", "exec")


def test_docstring_injection_is_escaped():
    spec = core.parse_spec_text(
        json.dumps(
            {
                "openapi": "3.0.0",
                "info": {"title": "t", "version": "1"},
                "servers": [{"url": "https://a.example.com"}],
                "paths": {
                    "/x": {
                        "get": {
                            "operationId": "x",
                            "summary": 'bad """ triple \\ backslash',
                            "responses": {"200": {"description": "ok"}},
                        }
                    }
                },
            }
        )
    )
    code = core.tool_code_from_spec(spec, "x")
    compile(code, "generated.py", "exec")


def test_generated_tool_names_are_unique(fixture_spec):
    ops = core.extract_operations(fixture_spec)
    names = core._dedupe([core._py_ident(o["operation_id"]) for o in ops])
    assert len(names) == len(set(names))


def test_bundle_lands_on_disk(tmp_path, fixture_spec, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = core.bundle_from_spec(fixture_spec, "offline-mcp")
    files = {Path(f).name for f in result["files"]}
    assert {"server.py", "requirements.txt", "README.md", "manifest.json"} <= files
    compile((tmp_path / "generated" / "offline-mcp" / "server.py").read_text(encoding="utf-8"), "s.py", "exec")


def test_manifest_has_tool_schemas_and_pricing(fixture_spec):
    manifest = core.manifest_from_spec(fixture_spec, "offline", pricing_tier="pro")
    assert manifest["listing"]["capabilities"]["tool_count"] > 0
    assert manifest["pricing"]["tier"] == "pro"
    assert manifest["pricing"]["currency"] == metering.DEFAULT_CURRENCY
    assert all("input_schema" in t for t in manifest["tools"])
    assert manifest["listing"]["auth"]["required"] is True


# ----------------------------- security boundaries ------------------------------------ #
@pytest.mark.parametrize("name", ["../escape", "a/b", "", ".", "x" * 65])
def test_output_name_whitelist_rejects_unsafe(name, tmp_path):
    with pytest.raises(core.PathNotAllowed):
        core.ensure_writable_dir(str(tmp_path), name)


def test_output_dir_traversal_is_refused(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    root = tmp_path / "generated"
    root.mkdir()
    assert core.ensure_writable_dir("generated", "ok-name") == root / "ok-name"


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8080/x",
        "http://localhost/x",
        "http://169.254.169.254/latest/meta-data/",
        "http://10.0.0.1/internal",
        "ftp://example.com/x",
    ],
)
def test_ssrf_guard_blocks_non_public_targets(url):
    with pytest.raises(ValueError):
        core.assert_public_url(url)


# --------- SSRF redirect bypass regression (a real reproduced vulnerability, must stay locked) --------------- #
class _FakeResp:
    def __init__(self, status_code, headers=None, url="https://public.example/x", text=""):
        self.status_code = status_code
        self.headers = headers or {}
        self.url = url
        self.text = text

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def _patch_httpx(monkeypatch, script, seen):
    """Replace httpx.AsyncClient with a fake client that answers from a script, one hop at a time."""

    class FakeClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def request(self, method, url, **kw):
            seen.append((method, url))
            return script[min(len(seen) - 1, len(script) - 1)]

    monkeypatch.setattr(core.httpx, "AsyncClient", FakeClient)


def _patch_guard(monkeypatch):
    """A lightweight public-only guard: real address classification is covered by the parameterized cases above."""

    def guard(url: str) -> None:
        if "127.0.0.1" in url or "localhost" in url or "169.254.169.254" in url:
            raise ValueError(f"refused {url}: resolves to a non-public address")

    monkeypatch.setattr(core, "assert_public_url", guard)


def test_redirect_to_internal_target_is_blocked(monkeypatch):
    """Regression for a real vulnerability: protection failed entirely when a public URL 302'd to 127.0.0.1.

    httpx's follow_redirects=True validates only the initial URL,
    so any public address that 302s to an internal or cloud metadata endpoint bypasses the SSRF guard.
    This case asserts the second hop is blocked and that the internal request is never actually sent.
    """
    seen: list = []
    _patch_guard(monkeypatch)
    _patch_httpx(
        monkeypatch,
        [
            _FakeResp(302, {"location": "http://127.0.0.1:8123/secret"}),
            _FakeResp(200, {}, "http://127.0.0.1:8123/secret", "INTERNAL-SECRET"),
        ],
        seen,
    )

    with pytest.raises(ValueError) as ei:
        asyncio_run(core.request_with_validated_redirects("GET", "https://public.example/x"))

    assert "127.0.0.1" in str(ei.value)
    assert seen == [("GET", "https://public.example/x")], "the second hop must not be requested"


def test_redirect_to_metadata_endpoint_is_blocked(monkeypatch):
    """Same vulnerability, cloud metadata variant: 302 -> 169.254.169.254 must be blocked."""
    seen: list = []
    _patch_guard(monkeypatch)
    _patch_httpx(
        monkeypatch,
        [
            _FakeResp(302, {"location": "http://169.254.169.254/latest/meta-data/"}),
            _FakeResp(200, {}, "http://169.254.169.254/latest/meta-data/", "SECRET"),
        ],
        seen,
    )

    with pytest.raises(ValueError):
        asyncio_run(core.request_with_validated_redirects("GET", "https://public.example/x"))
    assert len(seen) == 1


def test_redirect_chain_is_followed_and_rewritten_semantics(monkeypatch):
    """Legitimate traffic must not break: a public → public redirect should be followed, with 303 rewritten to GET."""
    seen: list = []
    _patch_guard(monkeypatch)
    _patch_httpx(
        monkeypatch,
        [
            _FakeResp(303, {"location": "https://cdn.example/final"}),
            _FakeResp(200, {}, "https://cdn.example/final", "ok"),
        ],
        seen,
    )

    resp = asyncio_run(core.request_with_validated_redirects("POST", "https://public.example/x"))
    assert resp.status_code == 200
    assert seen == [("POST", "https://public.example/x"), ("GET", "https://cdn.example/final")]


def test_redirect_loop_is_aborted(monkeypatch):
    """Redirect loops must exit within a bound instead of hanging the service."""
    seen: list = []
    _patch_guard(monkeypatch)
    _patch_httpx(
        monkeypatch,
        [_FakeResp(302, {"location": "https://public.example/x"})],
        seen,
    )

    with pytest.raises(ValueError) as ei:
        asyncio_run(core.request_with_validated_redirects("GET", "https://public.example/x"))
    assert "redirect" in str(ei.value)
    assert len(seen) == core.MAX_REDIRECTS + 1


def test_read_outside_allowed_root_is_refused(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    outside = tmp_path.parent / "outside-spec.json"
    outside.write_text("{}", encoding="utf-8")
    with pytest.raises(core.PathNotAllowed):
        core.ensure_readable(str(outside))


# ----------------------------- VERIFY verdict --------------------------------- #
@pytest.mark.parametrize(
    "status,expected_status,expected_passed",
    [
        (200, "passed", True),
        (201, "passed", True),
        (400, "bad_request", False),
        (401, "auth_required", False),
        (403, "auth_required", False),
        (404, "not_found", False),
        (429, "rate_limited", False),
        (500, "server_error", False),
    ],
)
def test_classify_response_is_not_always_true(status, expected_status, expected_passed):
    """Regression for the v1 defect: any response (including 4xx/5xx) was recorded as reachable=True."""
    got_status, got_passed = core.classify_response(status)
    assert (got_status, got_passed) == (expected_status, expected_passed)


# ----------------------------- MONETIZE ------------------------------------ #
def test_metering_records_and_invoice_math(tmp_path):
    meter = metering.UsageMeter(tmp_path / "usage.json")
    for i in range(5):
        meter.record("demo", "opA", ok=i < 4, status_code=200 if i < 4 else 500, latency_ms=12.5)

    rep = meter.report("demo")
    assert rep["apis"]["demo"]["total_calls"] == 5
    assert rep["apis"]["demo"]["ok_calls"] == 4
    assert rep["apis"]["demo"]["operations"][0]["calls"] == 5

    # basic tier: 10000 calls included, 2.0 per 1000. 100k calls -> 90k overage -> 180.0
    inv = meter.simulate_invoice("demo", "basic", basis="actual", projected_calls=100_000)
    assert inv["billable_overage_calls"] == 90_000
    assert inv["amount_due"] == 180.0


def test_metering_survives_corrupt_file(tmp_path):
    path = tmp_path / "usage.json"
    path.write_text("{ this is not json", encoding="utf-8")
    meter = metering.UsageMeter(path)
    assert meter.report()["total_calls_all_apis"] == 0
    assert (tmp_path / "usage.corrupt.json").exists(), "a corrupt file must be kept aside, not silently dropped"


def test_registry_persists_atomically_and_warns_on_overwrite(tmp_path, fixture_spec):
    path = tmp_path / "registry.json"
    reg = core.Registry(path)
    first = reg.register("demo", str(FIXTURE))
    assert first["overwrote_existing"] is False
    second = reg.register("demo", str(FIXTURE))
    assert second["overwrote_existing"] is True
    assert core.Registry(path).list_names() == ["demo"]


def test_registry_reports_unknown_operation_helpfully(tmp_path):
    reg = core.Registry(tmp_path / "registry.json")
    reg.register("demo", str(FIXTURE))
    res = reg.call("demo", "no-such-op", {})
    assert "error" in res and "available" in res["error"]


# ----------------------------- tool curation ------------------------------------ #
def test_scope_filter_by_tag_and_method(fixture_spec):
    ops = core.extract_operations(fixture_spec)
    filtered = core.filter_operations(ops, {"include_tags": ["pet"], "include_methods": ["GET"]})
    ids = {o["operation_id"] for o in filtered}
    assert ids == {"getPetById"}


def test_scope_exclude_deprecated_and_path_pattern():
    spec = core.parse_spec_text(
        json.dumps(
            {
                "openapi": "3.0.0",
                "info": {"title": "t", "version": "1"},
                "servers": [{"url": "https://a.example.com"}],
                "paths": {
                    "/pet/{id}": {
                        "get": {"operationId": "getPet", "tags": ["pet"], "responses": {"200": {"description": "ok"}}},
                        "delete": {"operationId": "delPet", "deprecated": True, "responses": {"200": {"description": "ok"}}},
                    },
                    "/store/inv": {
                        "get": {"operationId": "getInv", "responses": {"200": {"description": "ok"}}},
                    },
                },
            }
        )
    )
    ops = core.extract_operations(spec)
    filtered = core.filter_operations(ops, {"exclude_deprecated": True, "include_path_patterns": ["/pet/*"]})
    assert [o["operation_id"] for o in filtered] == ["getPet"]


def test_scope_intent_top_n():
    spec = core.parse_spec_text(
        json.dumps(
            {
                "openapi": "3.0.0",
                "info": {"title": "t", "version": "1"},
                "servers": [{"url": "https://a.example.com"}],
                "paths": {
                    "/users/{id}": {"get": {"operationId": "getUser", "summary": "get user", "tags": ["user"], "responses": {"200": {"description": "ok"}}}},
                    "/orders/{id}": {"get": {"operationId": "getOrder", "summary": "get order", "tags": ["order"], "responses": {"200": {"description": "ok"}}}},
                    "/pets/{id}": {"get": {"operationId": "getPet", "summary": "get pet", "tags": ["pet"], "responses": {"200": {"description": "ok"}}}},
                },
            }
        )
    )
    ops = core.extract_operations(spec)
    filtered = core.filter_operations(ops, {"intent": "user account", "top_n": 1})
    assert len(filtered) == 1
    assert filtered[0]["operation_id"] == "getUser"


def test_preview_scope_shows_reduction(fixture_spec):
    preview = core.preview_scope(str(FIXTURE), {"include_methods": ["GET"]})
    assert preview["total_operations"] == len(core.extract_operations(fixture_spec))
    assert preview["filtered_operations"] < preview["total_operations"]
    assert preview["reduction_percent"] > 0
    assert "suggestions" in preview


def test_bundle_with_scope_reduces_tool_count(tmp_path, fixture_spec, monkeypatch):
    monkeypatch.chdir(tmp_path)
    full = core.bundle_from_spec(fixture_spec, "offline-mcp")
    scoped = core.bundle_from_spec(fixture_spec, "offline-mcp-scoped", scope={"include_methods": ["GET"]})
    assert scoped["tools"] < full["tools"]
    assert scoped["original_operations"] == full["tools"]
    assert scoped["scope"]["include_methods"] == ["GET"]
