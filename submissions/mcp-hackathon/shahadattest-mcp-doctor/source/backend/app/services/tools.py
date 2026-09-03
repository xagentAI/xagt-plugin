from typing import Any


def to_snake(name: str) -> str:
    out = "".join("_" + c.lower() if c.isupper() else c for c in name).strip("_")
    return out.replace("-", "_").replace(" ", "_")


def generate_tools(endpoints: list[dict[str, Any]]) -> list[dict[str, Any]]:
    tools = []
    for ep in endpoints:
        op = ep.get("operation_id") or "operation"
        name = to_snake(op)
        props: dict[str, Any] = {}
        req: list[str] = []
        for p in ep.get("parameters") or []:
            if not isinstance(p, dict):
                continue
            pname = p.get("name", "arg")
            props[pname] = {"type": (p.get("schema") or {}).get("type", "string"),
                            "description": p.get("description", "")}
            if p.get("required"):
                req.append(pname)
        tools.append({"name": name, "description": (ep.get("description") or ep.get("summary") or f"{ep['method']} {ep['path']}").strip()[:300],
                      "inputSchema": {"type": "object", "properties": props, "required": req},
                      "outputSchema": {"type": "object"},
                      "operation_id": op, "method": ep["method"], "path": ep["path"]})
    return tools
