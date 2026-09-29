"""历史保留策略纯函数：条数裁剪与 TTL 的删除边界计算（v0.3，opt-in）。

只放纯函数与 env 解析，不碰任何存储实现：InMemoryStore 与 SqliteStore 共用
同一套"轮边界对齐"规则，保证两种实现的裁剪结果逐字节一致。

轮（round）的定义：一条 role == "user" 的消息到下一条 user 消息之前为一轮；
历史开头的非 user 消息归入"第 0 轮"，与相邻轮同生共死。
为什么必须按轮裁剪：assistant(tool_calls) 与其后的 tool 消息必须成对出现，
从中间切开后发给 OpenAI 兼容接口会直接 400（详见 walkthrough 第 13 章）。
"""

from __future__ import annotations

import os
import warnings
from datetime import UTC, datetime

_MAX_ENV = "YAI_HISTORY_MAX_MESSAGES"
_TTL_ENV = "YAI_HISTORY_TTL_SECONDS"


def utc_now() -> datetime:
    """统一 UTC 时钟；SQLite 的 CURRENT_TIMESTAMP 同为 UTC 文本，可直接比较。"""
    return datetime.now(UTC)


def _parse_positive_int(raw: str | None, env_name: str) -> int | None:
    """解析正整数环境变量。

    未设置/空白 -> None（静默，等同未配置）；
    0/负数/非整数 -> None + warning（不崩、不静默、不裁剪）。
    """
    if raw is None or not raw.strip():
        return None
    try:
        value = int(raw.strip())
    except ValueError:
        warnings.warn(
            f"{env_name}={raw!r} 不是合法整数，忽略（不裁剪历史）", stacklevel=2
        )
        return None
    if value <= 0:
        warnings.warn(
            f"{env_name}={value} 必须为正整数，忽略（不裁剪历史）", stacklevel=2
        )
        return None
    return value


def retention_from_env(
    env: dict[str, str] | None = None,
) -> tuple[int | None, int | None]:
    """读历史保留策略，返回 (max_messages, ttl_seconds)，未配置项为 None。

    env=None 读真实 os.environ；测试注入假字典，绝不碰真实环境变量。
    这是两个 Store 与 serve_example 共用的唯一 env 解析入口。
    """
    environ = os.environ if env is None else env
    return (
        _parse_positive_int(environ.get(_MAX_ENV), _MAX_ENV),
        _parse_positive_int(environ.get(_TTL_ENV), _TTL_ENV),
    )


def _next_round_start(roles: list[str], start: int) -> int | None:
    """从 start（含）向后找第一个轮首下标（role == "user"），找不到返回 None。"""
    for i in range(start, len(roles)):
        if roles[i] == "user":
            return i
    return None


def _prev_round_start(roles: list[str], start: int) -> int | None:
    """从 start（含）向前找最近的轮首下标；start 允许等于 len（整体过期场景）。"""
    for i in range(min(start, len(roles) - 1), -1, -1):
        if roles[i] == "user":
            return i
    return None


def count_cut(roles: list[str], max_messages: int | None) -> int | None:
    """条数裁剪：返回删除上界 k（删 [0, k)），不裁返回 None。

    候选边界 = len(roles) - max_messages，再向后对齐到轮首：
    - 对齐保证删除点落在一轮开头，不切散 assistant(tool_calls)/tool 配对；
    - 找不到后续轮首（只有一轮、或单轮自身超限）-> 不裁，宁可超限也不破坏序列；
    - max_messages 是"上限"而非"目标值"，对齐后实际保留条数可能少于上限。
    """
    if max_messages is None or max_messages <= 0:
        return None
    candidate = len(roles) - max_messages
    if candidate <= 0:
        return None
    k = _next_round_start(roles, candidate)
    if k is None or k <= 0:
        return None
    return k


def ttl_cut(roles: list[str], expired: list[bool]) -> int | None:
    """TTL 裁剪：返回删除上界 k（删 [0, k)），不裁返回 None。

    expired[i] 表示第 i 条是否已过期（严格早于 cutoff；恰好等于 cutoff 不算过期）。
    先数"从头开始连续过期"的条数 n，再把边界向前对齐到轮首：
    - 全部过期（n == len）：返回 len，整库清空——空历史合法，TTL 语义高于
      "至少保留最后一轮"（该约束只作用于条数裁剪）；
    - 否则边界必须落在轮首且 k > 0；只过期到首轮中间（k=0）则不裁，避免孤儿 tool。
    """
    n = 0
    for is_expired in expired:
        if not is_expired:
            break
        n += 1
    if n == 0:
        return None
    if n == len(roles):
        return n
    k = _prev_round_start(roles, n)
    if k is None or k <= 0:
        return None
    return k
