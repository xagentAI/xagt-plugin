"""Agent fingerprint: code/model/prompt/tools/skills/config bound to every proof."""
from .hashing import h

def fingerprint(agent: dict) -> str:
    material = {k: agent.get(k) for k in
                ("agent_id", "code", "model", "prompt", "tools", "skills", "config", "env")}
    return h(material)

def materially_changed(a: dict, b: dict) -> bool:
    return fingerprint(a) != fingerprint(b)
