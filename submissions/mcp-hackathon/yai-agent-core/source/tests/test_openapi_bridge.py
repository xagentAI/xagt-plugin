"""OpenAPI 发现桥测试：spec 解析、$ref、发现命名、MockTransport 调用、鉴权、端到端。

离线原则：所有 HTTP 走 httpx.MockTransport；不触网、不依赖真实 Key。
"""

import ast
import json
import pathlib

import pytest

pytest.importorskip("httpx")  # 没装 [dev]/[openapi] extra 的环境整体跳过
import httpx  # noqa: E402

from yai_core import AgentCore, ModelResponse, ToolCallRequest  # noqa: E402
from yai_core.integrations.openapi import (  # noqa: E402
    OpenApiSpecConfig,
    OpenApiToolBridge,
    attach_openapi_tools,
    config_from_env,
    load_spec,
    plan_operations,
    resolve_refs,
)

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "petstore.min.json"


@pytest.fixture
def spec_dict() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture
def resolved(spec_dict):
    spec, notes = resolve_refs(spec_dict)
    return spec, notes


def _handler_factory(captured: list):
    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        path = request.url.path
        if request.method == "GET" and path == "/api/v3/pets":
            return httpx.Response(200, json=[{"id": 1, "name": "旺财"}])
        if request.method == "POST" and path == "/api/v3/pets":
            return httpx.Response(201, json={"created": True})
        if request.method == "GET" and path.startswith("/api/v3/pets/"):
            if path.endswith("/999"):
                return httpx.Response(404, text="not found")
            return httpx.Response(200, json={"id": 7, "name": "小黑"})
        if request.method == "DELETE":
            return httpx.Response(204)
        if request.method == "POST" and path.startswith("/api/v3/echo/"):
            return httpx.Response(200, json=json.loads(request.content.decode()))
        return httpx.Response(404, text="unmatched")

    return handler


def _transport(captured):
    return httpx.MockTransport(_handler_factory(captured))


def _bridge(spec_dict, captured):
    return OpenApiToolBridge(
        OpenApiSpecConfig(spec=spec_dict, alias="rest"),
        transport=_transport(captured),
    )


# ---------- 1. $ref 展开与循环保留 ----------

def test_resolve_internal_refs_and_keep_cycles(resolved):
    spec, notes = resolved
    pet = spec["components"]["schemas"]["Pet"]
    assert pet["properties"]["name"]["type"] == "string"
    category = pet["properties"]["category"]  # 内部 $ref 已内联
    assert category["properties"]["name"]["type"] == "string"
    recursive = category["properties"]["children"]["items"]
    assert recursive.get("$ref") == "#/components/schemas/Category"  # 循环保留原样
    assert any("循环" in note for note in notes)


# ---------- 2. 发现与命名 ----------

def test_operation_naming(resolved):
    spec, _ = resolved
    plans, _ = plan_operations(spec, OpenApiSpecConfig(spec=spec))
    names = [p.name for p in plans]
    assert names == ["list_pets", "create_pet", "get_pets_pet_id", "delete_pet", "echo_body"]
    methods = {p.name: p.method for p in plans}
    assert methods["get_pets_pet_id"] == "GET"


# ---------- 3. 入参合并 ----------

def test_parameters_and_body_merge(resolved):
    spec, _ = resolved
    plans, _ = plan_operations(spec, OpenApiSpecConfig(spec=spec))
    by_name = {p.name: p for p in plans}

    list_plan = by_name["list_pets"]
    assert set(list_plan.query_params) == {"limit", "tags", "verbose"}
    assert "X-Trace" not in list_plan.input_schema["properties"]  # header 参数不暴露
    assert "limit" not in list_plan.input_schema.get("required", [])

    create_plan = by_name["create_pet"]
    assert set(create_plan.body_fields) == {"id", "name", "category"}
    assert create_plan.body_wrapped is False
    assert set(create_plan.input_schema["required"]) == {"id", "name"}
    # $ref 展开后的嵌套 schema 仍在
    assert create_plan.input_schema["properties"]["category"]["type"] == "object"

    get_one = by_name["get_pets_pet_id"]
    assert get_one.path_params == ("petId",)
    assert "petId" in get_one.input_schema["required"]  # path 参数强制必填

    echo = by_name["echo_body"]
    assert echo.body_wrapped is True and echo.body_fields == ("body",)
    assert "body" in echo.input_schema["required"]


# ---------- 4. read_only / 截断 / 前缀过滤 ----------

def test_read_only_filters_writes(resolved):
    spec, _ = resolved
    plans, _ = plan_operations(spec, OpenApiSpecConfig(spec=spec, read_only=True))
    assert all(p.method in {"GET", "HEAD"} for p in plans)
    assert "create_pet" not in [p.name for p in plans]


def test_max_operations_truncation(resolved):
    spec, _ = resolved
    plans, notes = plan_operations(spec, OpenApiSpecConfig(spec=spec, max_operations=2))
    assert len(plans) == 2
    assert any("截断" in note for note in notes)


def test_include_exclude_paths(resolved):
    spec, _ = resolved
    inc, _ = plan_operations(spec, OpenApiSpecConfig(spec=spec, include_paths=("/pets",)))
    assert all(p.path_template.startswith("/pets") for p in inc)
    exc, _ = plan_operations(spec, OpenApiSpecConfig(spec=spec, exclude_paths=("/pets",)))
    assert all(not p.path_template.startswith("/pets") for p in exc)


# ---------- 5. MockTransport 端到端调用 ----------

def _run(coro):
    import asyncio

    return asyncio.run(coro)


def test_get_query_bool_list_and_bearer(spec_dict, monkeypatch):
    monkeypatch.setenv("OPENAPI_AUTH_TOKEN", "test-token")
    captured: list = []
    bridge = _bridge(spec_dict, captured)
    specs = _run(bridge.connect())
    by_name = {s.name: s for s in specs}
    assert all(s.source == "openapi" for s in specs)

    result = _run(by_name["list_pets"].handler(limit=2, tags=["cat", "dog"], verbose=True))
    req = captured[-1]
    assert req.method == "GET"
    assert req.url.path == "/api/v3/pets"
    params = req.url.params
    assert params.get("limit") == "2"
    assert params.get_list("tags") == ["cat", "dog"]
    assert params.get("verbose") == "true"
    assert req.headers["Authorization"] == "Bearer test-token"
    assert result == [{"id": 1, "name": "旺财"}]
    _run(bridge.aclose())


def test_post_flattened_object_body(spec_dict, monkeypatch):
    monkeypatch.setenv("OPENAPI_AUTH_TOKEN", "test-token")
    captured: list = []
    bridge = _bridge(spec_dict, captured)
    specs = _run(bridge.connect())
    _run({s.name: s for s in specs}["create_pet"].handler(
        id=42, name="布偶", category={"name": "猫"}
    ))
    req = captured[-1]
    assert req.method == "POST" and req.url.path == "/api/v3/pets"
    assert json.loads(req.content) == {"id": 42, "name": "布偶", "category": {"name": "猫"}}
    assert req.headers["Content-Type"] == "application/json"
    _run(bridge.aclose())


def test_path_fill_204_404_and_wrapped_body(spec_dict, monkeypatch):
    monkeypatch.setenv("OPENAPI_AUTH_TOKEN", "test-token")
    captured: list = []
    bridge = _bridge(spec_dict, captured)
    specs = _run(bridge.connect())
    by_name = {s.name: s for s in specs}

    _run(by_name["get_pets_pet_id"].handler(petId=7))
    assert captured[-1].url.path == "/api/v3/pets/7"

    assert _run(by_name["delete_pet"].handler(petId=7)) == ""  # 204 → 空串

    with pytest.raises(RuntimeError, match="HTTP 404"):
        _run(by_name["get_pets_pet_id"].handler(petId=999))

    _run(by_name["echo_body"].handler(kind="x", body=["a", "b"]))  # 非 object body 包裹
    assert json.loads(captured[-1].content) == ["a", "b"]
    _run(bridge.aclose())


def test_apikey_header_auth(spec_dict, monkeypatch):
    monkeypatch.setenv("OPENAPI_AUTH_TOKEN", "test-token")
    key_spec = json.loads(json.dumps(spec_dict))
    key_spec["security"] = [{"keyHeader": []}]
    captured: list = []
    bridge = OpenApiToolBridge(
        OpenApiSpecConfig(spec=key_spec), transport=_transport(captured)
    )
    specs = _run(bridge.connect())
    _run({s.name: s for s in specs}["list_pets"].handler(limit=1))
    assert captured[-1].headers["X-Api-Key"] == "test-token"
    _run(bridge.aclose())


def test_missing_token_raises_at_call_time(spec_dict, monkeypatch):
    monkeypatch.delenv("OPENAPI_AUTH_TOKEN", raising=False)
    captured: list = []
    bridge = _bridge(spec_dict, captured)
    specs = _run(bridge.connect())  # 注册期不报错
    with pytest.raises(RuntimeError, match="OPENAPI_AUTH_TOKEN"):
        _run({s.name: s for s in specs}["list_pets"].handler())
    _run(bridge.aclose())


def test_missing_token_message_names_env_var(spec_dict, monkeypatch):
    """回归（40-review P3-1）：config_from_env 路径下缺令牌，报错要点名环境变量而非 None。"""
    monkeypatch.delenv("OPENAPI_AUTH_TOKEN", raising=False)
    env_cfg = config_from_env(env={"OPENAPI_SPEC_PATH": "spec.json"})
    cfg = OpenApiSpecConfig(spec=spec_dict, auth_token_env=env_cfg.auth_token_env)
    bridge = OpenApiToolBridge(cfg, transport=_transport([]))
    specs = _run(bridge.connect())
    with pytest.raises(RuntimeError, match="OPENAPI_AUTH_TOKEN"):
        _run({s.name: s for s in specs}["list_pets"].handler())
    _run(bridge.aclose())


def test_result_text_truncation(spec_dict, monkeypatch):
    monkeypatch.setenv("OPENAPI_AUTH_TOKEN", "t")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="x" * 20000, headers={"content-type": "text/plain"})

    bridge = OpenApiToolBridge(
        OpenApiSpecConfig(spec=spec_dict, max_result_chars=100),
        transport=httpx.MockTransport(handler),
    )
    specs = _run(bridge.connect())
    out = _run({s.name: s for s in specs}["list_pets"].handler())
    assert out.endswith("…[truncated]") and len(out) == len("…[truncated]") + 100
    _run(bridge.aclose())


# ---------- 6. config_from_env / load_spec 校验 / YAML ----------

def test_config_from_env_states():
    assert config_from_env(env={}) is None
    cfg = config_from_env(
        env={"OPENAPI_SPEC_URL": "http://x/openapi.json", "OPENAPI_READ_ONLY": "yes"}
    )
    assert cfg.url == "http://x/openapi.json" and cfg.read_only is True
    cfg_path = config_from_env(env={"OPENAPI_SPEC_PATH": "spec.yaml"})
    assert str(cfg_path.path) == "spec.yaml"


def test_reject_swagger2_and_non_openapi3():
    with pytest.raises(ValueError, match="Swagger 2.0"):
        load_spec(OpenApiSpecConfig(spec={"swagger": "2.0", "paths": {}}))
    with pytest.raises(ValueError, match="3.x"):
        load_spec(OpenApiSpecConfig(spec={"openapi": "2.5"}))


def test_yaml_spec_loads(tmp_path):
    pytest.importorskip("yaml")
    p = tmp_path / "spec.yaml"
    p.write_text(
        "openapi: 3.0.3\ninfo:\n  title: T\n  version: '1.0'\n"
        "paths:\n  /ping:\n    get:\n      operationId: ping\n"
        "      summary: ping\n      responses:\n        '200':\n          description: ok\n",
        encoding="utf-8",
    )
    spec = load_spec(OpenApiSpecConfig(path=p))
    assert "/ping" in spec["paths"]


def test_missing_httpx_error_message(monkeypatch):
    """缺 httpx 时 connect() 的报错必须提示 extra 名（模拟 builtins 导入失败代价高，
    这里做字符串契约校验：错误文案在源码中固定）。"""
    client_path = pathlib.Path(__file__).parents[1] / "src" / "yai_core" / (
        "integrations/openapi/client.py"
    )
    text = client_path.read_text(encoding="utf-8")
    assert "uv sync --extra openapi" in text


# ---------- 7. 注册进 AgentCore 的端到端 react ----------

class _ScriptedToolModel:
    def __init__(self):
        self.calls = 0

    async def achat(self, messages, tools=None, *, tier="standard"):
        self.calls += 1
        if self.calls == 1:
            return ModelResponse(
                content="",
                tool_calls=[ToolCallRequest(id="c1", name="list_pets", arguments={"limit": 1})],
            )
        return ModelResponse(content="查到了宠物")


def test_agent_core_end_to_end_with_openapi_tool(spec_dict, monkeypatch):
    monkeypatch.setenv("OPENAPI_AUTH_TOKEN", "test-token")
    captured: list = []
    core = AgentCore(_ScriptedToolModel())
    bridge = _run(
        attach_openapi_tools(core.registry, OpenApiSpecConfig(spec=spec_dict),
                             transport=_transport(captured))
    )
    assert "list_pets" in core.registry.describe()
    assert core.registry._tools["list_pets"].source == "openapi"

    import asyncio

    result = asyncio.run(core.run("列一下宠物"))
    assert result.final_text == "查到了宠物"
    event_types = [e.type.value for e in result.events]
    assert "tool_call" in event_types and "tool_result" in event_types
    assert captured[-1].url.path == "/api/v3/pets"
    _run(bridge.aclose())


# ---------- 8. 红线：openapi 模块顶层不得 import httpx / yaml ----------

@pytest.mark.parametrize(
    "relative",
    ["integrations/openapi/spec.py", "integrations/openapi/discovery.py",
     "integrations/openapi/client.py"],
)
def test_no_toplevel_third_party_imports(relative):
    path = pathlib.Path(__file__).parents[1] / "src" / "yai_core" / relative
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:  # 只检查模块顶层语句
        if isinstance(node, ast.Import):
            assert all(not a.name.startswith(("httpx", "yaml")) for a in node.names)
        if isinstance(node, ast.ImportFrom):
            assert node.module is None or not node.module.startswith(("httpx", "yaml"))
