"""评审期限流：每 IP 滑动窗口限流 Battery（v0.3，纯标准库）。

威胁模型（如实声明）：本模块只防"误刷"——手滑重试、爬虫、失控循环；
**不防**蓄意伪造 X-Forwarded-For 的分布式攻击（那需要鉴权/人机验证，超出 v0.3）。
客户端身份取 XFF 最左非空 IP（Render 边缘代理会附加 XFF），缺失回退对端地址。

TODO(v0.4)：全局兜底限流（跨实例/全实例总配额）暂不做——免费层单实例，
分布式计数属后续议题；目前只有每 IP 维度。
"""

from __future__ import annotations

import math
import os
import time
import warnings
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from threading import Lock

_ENABLED_ENV = "YAI_RATE_LIMIT_ENABLED"
_PER_MINUTE_ENV = "YAI_RATE_LIMIT_PER_MINUTE"
_WINDOW_ENV = "YAI_RATE_LIMIT_WINDOW_SECONDS"


def _truthy_enabled(raw: str | None) -> bool:
    """enabled 解析：未设置视为开启；显式 0/false/no/off 才关闭。"""
    if raw is None or not raw.strip():
        return True
    return raw.strip().lower() not in {"0", "false", "no", "off"}


def _parse_positive_int(raw: str | None, env_name: str, default: int) -> int:
    """正整数解析：未设置/空白回退默认（静默）；非法值回退默认 + warning。"""
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw.strip())
    except ValueError:
        warnings.warn(f"{env_name}={raw!r} 不是合法整数，回退默认值 {default}", stacklevel=2)
        return default
    if value <= 0:
        warnings.warn(f"{env_name}={value} 必须为正整数，回退默认值 {default}", stacklevel=2)
        return default
    return value


@dataclass
class RateLimitConfig:
    """限流配置；默认值（开启 / 30 次 / 60 秒）是对外承诺，改动须先改 10-plan。"""

    enabled: bool = True
    per_minute: int = 30
    window_seconds: int = 60
    time_func: Callable[[], float] = field(default=time.monotonic)

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> RateLimitConfig:
        """从环境变量构造；env=None 读真实 os.environ，测试注入假字典。"""
        environ = env if env is not None else os.environ
        return cls(
            enabled=_truthy_enabled(environ.get(_ENABLED_ENV)),
            per_minute=_parse_positive_int(
                environ.get(_PER_MINUTE_ENV), _PER_MINUTE_ENV, 30
            ),
            window_seconds=_parse_positive_int(
                environ.get(_WINDOW_ENV), _WINDOW_ENV, 60
            ),
        )


class SlidingWindowLimiter:
    """每 key 一个时间戳 deque；请求时先清窗口外时间戳，再判断是否超限。

    状态只在内存（进程重启清零），不落盘、不引 Redis。
    """

    def __init__(self, config: RateLimitConfig) -> None:
        self._per_minute = config.per_minute
        self._window = config.window_seconds
        self._time_func = config.time_func
        self._hits: dict[str, deque[float]] = {}
        # 防御性互斥：目标路由是 async 且 deque 操作无 await 间隙，单事件循环下
        # 理论原子；但 TestClient / 将来同步路由会跨线程，锁成本近乎为零。
        self._lock = Lock()

    def check(self, key: str) -> tuple[bool, int]:
        """返回 (是否放行, 超限时建议等待的整秒数)。"""
        now = self._time_func()
        with self._lock:
            hits = self._hits.setdefault(key, deque())
            # 窗口边界用 <= 清除：正好等于窗口的请求视为过期。
            cutoff = now - self._window
            while hits and hits[0] <= cutoff:
                hits.popleft()
            if len(hits) >= self._per_minute:
                oldest = hits[0]
                retry_after = max(1, math.ceil(oldest + self._window - now))
                return False, retry_after
            hits.append(now)
            return True, 0


def client_ip(x_forwarded_for: str | None, peer_host: str | None) -> str:
    """XFF 取最左非空段；缺失回退对端地址；再缺省 "unknown"。"""
    if x_forwarded_for:
        for part in x_forwarded_for.split(","):
            candidate = part.strip()
            if candidate:
                return candidate
    if peer_host:
        return peer_host
    return "unknown"
