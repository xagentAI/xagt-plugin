from typing import Any

AMBIGUOUS_PARAMS = {"q", "data", "info", "param", "arg", "x", "foo"}


def analyze_endpoints(endpoints: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    analyses: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []

    def add(sev: str, code: str, msg: str, ep: dict, fix: str = ""):
        issues.append({"severity": sev, "code": code, "message": msg,
                       "endpoint": f"{ep['method']} {ep['path']}",
                       "operation_id": ep["operation_id"], "suggested_repair": fix})

    for ep in endpoints:
        desc = (ep.get("description") or ep.get("summary") or "")
        params = ep.get("parameters") or []
        responses = ep.get("responses") or {}
        op_id = ep.get("operation_id") or ""
        # description quality
        desc_q = 100
        if not desc:
            desc_q -= 40
            add("medium", "MISSING_DESC", f"{ep['method']} {ep['path']} has no description", ep, "Add operation description")
        elif len(desc) < 20:
            desc_q -= 15
        # param description
        missing_pdesc = sum(1 for p in params if isinstance(p, dict) and not p.get("description"))
        if missing_pdesc:
            add("medium", "PARAM_NO_DESC", f"{missing_pdesc} parameter(s) without description on {ep['method']} {ep['path']}", ep, "Document parameters")
        # schema quality
        schema_q = 100
        has_2xx_schema = any(str(c).startswith("2") and isinstance(v, dict) and ("content" in v or "$ref" in v) for c, v in responses.items())
        if not has_2xx_schema and responses:
            schema_q -= 50
            add("high", "NO_RESPONSE_SCHEMA", f"{ep['method']} {ep['path']} lacks 2xx response schema", ep, "Add response content schema")
        elif not responses:
            schema_q -= 50
            add("high", "NO_RESPONSES", f"{ep['method']} {ep['path']} documents no responses", ep, "Document responses")
        # error docs
        err_q = 100
        has_4xx = any(str(c).startswith("4") for c in responses.keys())
        has_5xx = any(str(c).startswith("5") for c in responses.keys())
        if not has_4xx:
            err_q -= 30
            add("medium", "NO_4XX_DOC", f"{ep['method']} {ep['path']} documents no 4xx errors", ep, "Document 400/422 errors")
        if not has_5xx:
            err_q -= 10
        # usability
        agent_q = 100
        if not op_id or op_id.startswith("get__"):
            agent_q -= 10
            add("low", "MISSING_OP_ID", f"{ep['method']} {ep['path']} has weak operationId", ep, "Set clear operationId")
        for p in params:
            if isinstance(p, dict) and p.get("name") in AMBIGUOUS_PARAMS:
                agent_q -= 10
                add("low", "AMBIGUOUS_PARAM", f"Ambiguous parameter name '{p.get('name')}' on {ep['method']} {ep['path']}", ep, "Rename to meaningful name")
                break
        if not any(isinstance(p, dict) and p.get("schema") for p in params) and not ep.get("requestBody"):
            pass
        analyses.append({
            "method": ep["method"], "path": ep["path"], "operation_id": op_id,
            "description_quality": max(0, desc_q),
            "schema_quality": max(0, schema_q),
            "error_documentation": max(0, err_q),
            "agent_usability": max(0, agent_q),
            "safe_to_auto_test": ep["method"] in ("GET", "HEAD", "OPTIONS"),
        })
    return analyses, issues
