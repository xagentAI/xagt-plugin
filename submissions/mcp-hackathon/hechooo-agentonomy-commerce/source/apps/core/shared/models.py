from dataclasses import asdict, dataclass, field


@dataclass
class ToolCallSummary:
    tool_name: str
    status: str
    detail: str
    payload: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)
