from __future__ import annotations

from yai_core.types import ChatMessage


class Context:
    """单次运行的对话上下文。v0.1 用朴素字符估算做 token 预算，v2 换 tiktoken。"""

    def __init__(self, system_prompt: str, *, max_chars: int = 24000) -> None:
        self.max_chars = max_chars
        self.messages: list[ChatMessage] = [ChatMessage(role="system", content=system_prompt)]

    def add(self, message: ChatMessage) -> None:
        self.messages.append(message)
        self._compact()

    def _compact(self) -> None:
        """超预算时丢弃最旧的整轮历史：system 永留，且至少保留最后一轮。

        v0.3 修复：旧实现按下标逐个丢，可能从 assistant(tool_calls)/tool 配对中间
        切开，发给 OpenAI 兼容接口会直接 400。现改为把候补丢弃边界**向后对齐到
        轮首**（role == "user"），规则与 memory/retention.py 同源；为避免 kernel
        反向依赖 memory 包，这里保留一份私有实现，两处改动必须同步（第 13 章讲义）。
        候补边界之后没有新一轮时，宁可超预算也保留最后一轮（含其工具消息）。
        """
        total = sum(len(m.content) for m in self.messages)
        i = 1
        while total > self.max_chars and i < len(self.messages) - 1:
            total -= len(self.messages[i].content)
            i += 1
        if i <= 1:
            return
        aligned = i
        while aligned < len(self.messages) and self.messages[aligned].role != "user":
            aligned += 1
        if aligned >= len(self.messages):
            # 候补边界之后没有新一轮：保留最后一轮，不做裁剪。
            return
        self.messages = [self.messages[0], *self.messages[aligned:]]

    def llm_messages(self) -> list[dict]:
        return [m.to_llm_dict() for m in self.messages]
