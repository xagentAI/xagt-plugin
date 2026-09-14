"""限流 Battery 测试：滑动窗口、429 + Retry-After、GET 放行、假时钟全离线。

统一范式：TestClient + 计数版 ScriptedModel + 假时钟（now 列表），禁止 time.sleep。
"""

from __future__ import annotations

import warnings

from fastapi.testclient import TestClient

from yai_core import AgentCore, ModelResponse, build_spec
from yai_core.batteries.fastapi_server import RateLimitConfig, create_app
from yai_core.batteries.fastapi_server.ratelimit import SlidingWindowLimiter, client_ip


class CountingModel:
    """记录 achat 调用次数：断言被限请求一分模型钱都不花。"""

    def __init__(self) -> None:
        self.calls = 0

    async def achat(self, messages, tools=None, *, tier="standard"):
        self.calls += 1
        return ModelResponse(content="好的")


def list_notes() -> list:
    """列出全部笔记。"""
    return [{"id": 1, "title": "Core 骨架"}]


class FakeClock:
    """可推进的假时钟（秒）；测试推进时间而不是 sleep 等真实窗口。"""

    def __init__(self) -> None:
        self.now = [0.0]

    def __call__(self) -> float:
        return self.now[0]

    def advance(self, seconds: float) -> None:
        self.now[0] += seconds


def make_client(model: CountingModel, config: RateLimitConfig | None) -> TestClient:
    core = AgentCore(model)
    core.register_tools([build_spec(list_notes)])
    return TestClient(create_app(core, rate_limit=config))


def limited_config(clock: FakeClock, per_minute: int = 2) -> RateLimitConfig:
    """小配额便于测试：per_minute 次 200，之后 429。"""
    return RateLimitConfig(
        enabled=True, per_minute=per_minute, window_seconds=60, time_func=clock
    )


# ---------- 1/2. 超限 429 + Retry-After；推进假时钟后恢复 ----------

def test_over_limit_returns_429_then_recovers(monkeypatch) -> None:
    monkeypatch.setenv("YAI_GIT_COMMIT", "0" * 40)
    clock = FakeClock()
    model = CountingModel()
    client = make_client(model, limited_config(clock, per_minute=2))

    assert client.post("/v1/agent/run", json={"task": "1"}).status_code == 200
    assert client.post("/v1/agent/run", json={"task": "2"}).status_code == 200

    limited = client.post("/v1/agent/run", json={"task": "3"})
    assert limited.status_code == 429
    body = limited.json()
    assert body["error"] == "rate_limited"
    assert isinstance(body["retry_after"], int) and body["retry_after"] >= 1
    assert limited.headers["Retry-After"] == str(body["retry_after"])  # 同一计算源

    clock.advance(seconds=61)  # 越过窗口：滑动窗口语义下恢复
    assert client.post("/v1/agent/run", json={"task": "4"}).status_code == 200


# ---------- 3. 429 状态下三个 GET 端点仍 200（评审硬门槛） ----------

def test_get_endpoints_never_limited(monkeypatch) -> None:
    monkeypatch.setenv("YAI_GIT_COMMIT", "0" * 40)
    monkeypatch.setenv("YAI_PROJECT_SLUG", "yai-test")
    clock = FakeClock()
    client = make_client(CountingModel(), limited_config(clock, per_minute=1))

    assert client.post("/v1/agent/run", json={"task": "1"}).status_code == 200
    assert client.post("/v1/agent/run", json={"task": "2"}).status_code == 429

    assert client.get("/health").status_code == 200
    assert client.get("/.well-known/xagent-verification.json").status_code == 200
    assert client.get("/v1/tools").status_code == 200


# ---------- 4. enabled=False 全放行 ----------

def test_disabled_config_allows_everything(monkeypatch) -> None:
    monkeypatch.setenv("YAI_GIT_COMMIT", "0" * 40)
    clock = FakeClock()
    config = RateLimitConfig(
        enabled=False, per_minute=1, window_seconds=60, time_func=clock
    )
    client = make_client(CountingModel(), config)
    for _i in range(5):
        assert client.post("/v1/agent/run", json={"task": "x"}).status_code == 200


# ---------- 5. 每 IP 隔离 ----------

def test_per_ip_isolation(monkeypatch) -> None:
    monkeypatch.setenv("YAI_GIT_COMMIT", "0" * 40)
    clock = FakeClock()
    client = make_client(CountingModel(), limited_config(clock, per_minute=1))

    ok_a = client.post(
        "/v1/agent/run", json={"task": "a"}, headers={"X-Forwarded-For": "1.1.1.1"}
    )
    ok_b = client.post(
        "/v1/agent/run", json={"task": "b"}, headers={"X-Forwarded-For": "2.2.2.2"}
    )
    limited_a = client.post(
        "/v1/agent/run", json={"task": "a2"}, headers={"X-Forwarded-For": "1.1.1.1"}
    )
    assert ok_a.status_code == 200
    assert ok_b.status_code == 200  # 另一个 IP 有独立配额
    assert limited_a.status_code == 429  # 同一 IP 超限


# ---------- 6. client_ip() 六种输入 ----------

def test_client_ip_inputs() -> None:
    assert client_ip(None, "10.0.0.1") == "10.0.0.1"  # 无 XFF：回退对端
    assert client_ip("1.2.3.4", "10.0.0.1") == "1.2.3.4"  # 单级
    assert client_ip("1.2.3.4, 5.6.7.8", "10.0.0.1") == "1.2.3.4"  # 多级取最左
    assert client_ip(" , 5.6.7.8", "10.0.0.1") == "5.6.7.8"  # 含空段：跳过取非空
    assert client_ip("  ,  ", "10.0.0.1") == "10.0.0.1"  # 全空：回退对端
    assert client_ip(None, None) == "unknown"  # 双缺省


# ---------- 7. 被限请求不触达模型 ----------

def test_limited_request_never_reaches_model(monkeypatch) -> None:
    monkeypatch.setenv("YAI_GIT_COMMIT", "0" * 40)
    clock = FakeClock()
    model = CountingModel()
    client = make_client(model, limited_config(clock, per_minute=2))

    statuses = [
        client.post("/v1/agent/run", json={"task": str(i)}).status_code
        for i in range(4)
    ]
    assert statuses == [200, 200, 429, 429]
    assert model.calls == 2  # 4 次请求只调用 2 次模型


# ---------- 8. env 三态与非法值 ----------

def test_from_env_states(monkeypatch) -> None:
    monkeypatch.delenv("YAI_RATE_LIMIT_ENABLED", raising=False)
    monkeypatch.delenv("YAI_RATE_LIMIT_PER_MINUTE", raising=False)
    monkeypatch.delenv("YAI_RATE_LIMIT_WINDOW_SECONDS", raising=False)
    config = RateLimitConfig.from_env()
    assert (config.enabled, config.per_minute, config.window_seconds) == (True, 30, 60)

    config = RateLimitConfig.from_env(
        env={
            "YAI_RATE_LIMIT_ENABLED": "0",
            "YAI_RATE_LIMIT_PER_MINUTE": "10",
            "YAI_RATE_LIMIT_WINDOW_SECONDS": "30",
        }
    )
    assert (config.enabled, config.per_minute, config.window_seconds) == (False, 10, 30)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        config = RateLimitConfig.from_env(
            env={"YAI_RATE_LIMIT_PER_MINUTE": "-3", "YAI_RATE_LIMIT_WINDOW_SECONDS": "x"}
        )
        assert (config.enabled, config.per_minute, config.window_seconds) == (True, 30, 60)
        assert len(caught) == 2


# ---------- 9. 窗口边界：正好等于窗口的请求视为过期 ----------

def test_window_boundary_inclusive_expiry(monkeypatch) -> None:
    monkeypatch.setenv("YAI_GIT_COMMIT", "0" * 40)
    clock = FakeClock()
    limiter = SlidingWindowLimiter(limited_config(clock, per_minute=1))

    allowed, _ = limiter.check("1.1.1.1")
    assert allowed is True
    clock.advance(seconds=60)  # 恰好等于窗口：<= 清除语义下视为过期
    allowed, retry_after = limiter.check("1.1.1.1")
    assert allowed is True

    # 超限瞬间 retry_after 至少为 1
    clock.now[0] = 60.5
    limiter.check("2.2.2.2")
    allowed, retry_after = limiter.check("2.2.2.2")
    assert allowed is False and retry_after >= 1


# ---------- 10. 默认开启不破坏既有零配置调用 ----------

def test_default_create_app_still_works(monkeypatch) -> None:
    monkeypatch.setenv("YAI_GIT_COMMIT", "0" * 40)
    monkeypatch.delenv("YAI_RATE_LIMIT_ENABLED", raising=False)
    core = AgentCore(CountingModel())
    core.register_tools([build_spec(list_notes)])
    client = TestClient(create_app(core))  # 与 test_battery_api.py 同款零配置调用
    assert client.get("/health").status_code == 200
    assert client.post("/v1/agent/run", json={"task": "你好"}).status_code == 200
