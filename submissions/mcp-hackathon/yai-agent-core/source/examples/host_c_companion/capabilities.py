"""宿主 C：极简 AI 陪伴应用能力层 —— AMBRACE（拥爱）的缩影。

这是 YAI 未来回流 AMBRACE 后的形态预演：
陪伴业务（状态、记忆、心情、主动关怀）照常写成普通函数，
Agent 能力（该回忆什么、何时主动关心、怎么串起来）由 Core 自适应提供。
"""

from __future__ import annotations

from datetime import date

_PROFILE = {"name": "小拥", "mood": "平静", "energy": 62, "bond_days": 128}

_MOOD_LOG = [
    {"day": "09-06", "mood": "焦虑", "note": "担心三个比赛来不及"},
    {"day": "09-07", "mood": "开心", "note": "YAI Core 骨架跑通了"},
]

_MEMORIES = [
    {"id": 1, "kind": "偏好", "content": "深夜写代码时喜欢听 lofi，不喜欢被催进度"},
    {"id": 2, "kind": "约定", "content": "每周五晚上一起做一周复盘"},
    {"id": 3, "kind": "经历", "content": "一起从零做 AMBRACE，报名了三个比赛"},
]


def get_companion_profile() -> dict:
    """获取陪伴对象当前的状态档案。"""
    return dict(_PROFILE)


def recall_memories(keyword: str = "") -> list[dict]:
    """回忆与关键词相关的长期记忆，关键词为空时返回全部。"""
    if not keyword:
        return list(_MEMORIES)
    return [m for m in _MEMORIES if keyword in m["kind"] or keyword in m["content"]]


def save_memory(kind: str = "日常", content: str = "") -> dict:
    """把一条新的长期记忆写入陪伴记忆库。"""
    item = {"id": len(_MEMORIES) + 1, "kind": kind, "content": content}
    _MEMORIES.append(item)
    return {"saved": True, "memory": item, "total": len(_MEMORIES)}


def log_mood(mood: str = "平静", note: str = "") -> dict:
    """记录此刻心情，并返回陪伴状态摘要。"""
    entry = {"day": date.today().strftime("%m-%d"), "mood": mood, "note": note}
    _MOOD_LOG.append(entry)
    return {"logged": entry, "profile": dict(_PROFILE), "recent_moods": _MOOD_LOG[-3:]}


def suggest_care_action() -> dict:
    """根据陪伴状态给出一条主动关怀建议（AMBRACE 主动行为的最小雏形）。"""
    if _PROFILE["energy"] < 70:
        action = "提醒休息，陪他聊五分钟而不是推进任务"
        reason = "能量值偏低，优先安抚情绪"
    elif _PROFILE["bond_days"] > 100:
        action = "翻出一条共同记忆，主动开启回忆话题"
        reason = "羁绊天数较长，用共同经历增强连接"
    else:
        action = "轻打个招呼，问问今天过得怎样"
        reason = "状态平稳，常规陪伴即可"
    return {"action": action, "reason": reason, "based_on": dict(_PROFILE)}
