"""Deterministic evaluator: exact-match on duplicate boolean. No LLM judge."""
def evaluate(challenge: dict, output: dict) -> bool:
    try:
        exp = bool(challenge["expected"]["duplicate"])
        got = output.get("duplicate")
        if isinstance(got, str):
            got = got.strip().lower() in ("true", "yes", "1", "duplicate")
        return bool(got) is exp
    except Exception:
        return False
