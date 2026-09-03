from typing import Any

WEIGHTS = {"schema": 25, "docs": 15, "consistency": 15, "errors": 15, "reliability": 15, "usability": 15}


def compute_score(analyses: list[dict], issues: list[dict], test_results: list[dict] | None = None) -> dict[str, Any]:
    n = max(1, len(analyses))
    avg = lambda k: sum(a.get(k, 0) for a in analyses) / n
    schema = round(avg("schema_quality") / 100 * WEIGHTS["schema"])
    docs = round(avg("description_quality") / 100 * WEIGHTS["docs"])
    usability = round(avg("agent_usability") / 100 * WEIGHTS["usability"])
    errors = round(avg("error_documentation") / 100 * WEIGHTS["errors"])
    # consistency: penalize critical/high schema issues
    crit = sum(1 for i in issues if i["severity"] in ("critical", "high"))
    consistency = max(0, WEIGHTS["consistency"] - crit * 5)
    # reliability from tests if present else neutral 10
    if test_results:
        passed = sum(1 for t in test_results if t.get("status") == "passed")
        reliability = round(passed / max(1, len(test_results)) * WEIGHTS["reliability"])
    else:
        reliability = 10
    total = schema + docs + consistency + errors + reliability + usability
    return {"overall": total,
            "breakdown": {"schema_quality": schema, "documentation": docs, "consistency": consistency,
                          "error_handling": errors, "reliability": reliability, "agent_usability": usability}}
