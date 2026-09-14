"""宿主 A：一个极简笔记应用的业务能力层。

注意：这里没有任何 Agent 代码——只有普通业务函数。
YAI Agent Core 通过内省自动把它们变成可被 Agent 调用的工具。
"""

from __future__ import annotations

_NOTES: list[dict] = [
    {"id": 1, "title": "Core 骨架", "content": "完成 SPI 四契约与 Agent Loop", "tag": "工作"},
    {"id": 2, "title": "比赛清单", "content": "X-Agent 0919 截止，需要部署健康端点", "tag": "工作"},
    {"id": 3, "title": "购物", "content": "买咖啡豆和牛奶", "tag": "生活"},
]


def list_notes(tag: str = "") -> list[dict]:
    """列出全部笔记，可按标签筛选。"""
    if tag:
        return [n for n in _NOTES if n["tag"] == tag]
    return _NOTES


def search_notes(keyword: str) -> list[dict]:
    """按关键词搜索笔记标题与正文。"""
    return [n for n in _NOTES if keyword in n["title"] or keyword in n["content"]]


def count_notes() -> int:
    """统计笔记总数。"""
    return len(_NOTES)
