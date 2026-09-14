"""示例共用：无 API Key 时使用的脚本化离线模型（演示"零配置可跑"）。"""

from yai_core import ModelResponse, ToolCallRequest


class OfflineScriptedModel:
    """行为：规划轮先给计划；第一次拿到工具清单时调用首个工具；之后收尾。"""

    def __init__(self) -> None:
        self.calls = 0
        self._tool_used = False

    async def achat(self, messages, tools=None, *, tier="standard"):
        self.calls += 1
        # 第一次拿到工具时调用第一个工具（react 首轮 / plan 的执行首轮都适用）
        if tools and not self._tool_used:
            self._tool_used = True
            first_tool = tools[0]["function"]["name"]
            return ModelResponse(
                content="",
                tool_calls=[ToolCallRequest(id="demo-1", name=first_tool, arguments={})],
            )
        # 规划轮（无工具）：输出步骤计划
        if self.calls == 1:
            return ModelResponse(content="1. 筛选目标数据\n2. 调用宿主能力执行\n3. 整理最终结果")
        # 收尾：基于工具观察回答
        last_tool_msg = next((m for m in reversed(messages) if m["role"] == "tool"), None)
        observed = last_tool_msg["content"] if last_tool_msg else "（无工具结果）"
        return ModelResponse(content=f"离线演示完成，宿主能力返回：{observed[:120]}")
