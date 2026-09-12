# -*- coding: utf-8 -*-
"""Unit tests for the dual-engine code review service."""
import json

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.diff_parser import parse_diff
from app.main import app
from app.reviewer import _extract_json
from app.rules_engine import detect_language, merge_findings, run_rules

client = TestClient(app)


# ── Meta endpoints ──────────────────────────────────────────────

def test_health_returns_commit():
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["commit"] == get_settings().commit


def test_verification_well_known():
    resp = client.get("/.well-known/xagent-verification.json")
    assert resp.status_code == 200
    body = resp.json()
    assert body["schemaVersion"] == 1
    assert body["slug"] == "kestarsheng-code-review-agent"
    assert "commit" in body


# ── Rule engine ─────────────────────────────────────────────────

def test_rules_detect_eval():
    code = "result = eval(user_input)"
    findings = run_rules(code, "python")
    ids = [f.rule_id for f in findings]
    assert "PY-S001" in ids


def test_rules_detect_hardcoded_secret():
    code = 'api_key = "sk-1234567890abcdef"'
    findings = run_rules(code, "python")
    ids = [f.rule_id for f in findings]
    assert "PY-S004" in ids


def test_rules_detect_sql_injection():
    code = 'cursor.execute(f"SELECT * FROM users WHERE id = {user_id}")'
    findings = run_rules(code, "python")
    ids = [f.rule_id for f in findings]
    assert "PY-S006" in ids


def test_rules_detect_js_innerhtml():
    code = "document.getElementById('x').innerHTML = userInput"
    findings = run_rules(code, "javascript")
    ids = [f.rule_id for f in findings]
    assert "JS-S002" in ids


def test_rules_detect_todo():
    code = "# TODO: fix this later\npass"
    findings = run_rules(code, "python")
    ids = [f.rule_id for f in findings]
    assert "X-M001" in ids


def test_rules_clean_code_no_findings():
    code = "def add(a: int, b: int) -> int:\n    return a + b"
    findings = run_rules(code, "python")
    security = [f for f in findings if f.severity == "critical"]
    assert len(security) == 0


def test_detect_language_python():
    assert detect_language("def foo():\n    pass", "python") == "python"
    assert detect_language("def foo():\n    pass", "") == "python"


def test_detect_language_javascript():
    assert detect_language("const x = 1", "js") == "javascript"
    assert detect_language("const x = 1", "") == "javascript"


def test_detect_language_java():
    assert detect_language("import java.util.List;", "") == "java"


def test_detect_language_go():
    assert detect_language("func main() {\n}", "") == "go"


def test_merge_findings_rule_only():
    rule_findings = run_rules("eval('1+1')", "python")
    merged = merge_findings(rule_findings, [], "eval('1+1')")
    assert any(m["source"] == "rule" for m in merged)


def test_merge_findings_confirmed():
    rule_findings = run_rules("eval('1+1')", "python")
    llm_issues = [
        {"severity": "critical", "category": "security", "line": 1,
         "title": "eval", "description": "RCE", "suggestion": "don't use eval"}
    ]
    merged = merge_findings(rule_findings, llm_issues, "eval('1+1')")
    assert any(m["source"] == "confirmed" for m in merged)


def test_list_rules_endpoint():
    resp = client.get("/v1/rules")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] > 10
    assert any(r["id"] == "PY-S001" for r in body["rules"])


def test_get_rule_detail_exists():
    resp = client.get("/v1/rules/PY-S001")
    assert resp.status_code == 200
    body = resp.json()
    assert body["rule_id"] == "PY-S001"
    assert "description" in body
    assert body["ok"] is True


def test_get_rule_detail_not_found():
    resp = client.get("/v1/rules/XX-X999")
    assert resp.status_code == 404


def test_explain_issue_provides_guidance():
    from app.reviewer import explain_issue

    result = explain_issue("py-s002")
    assert result["ok"] is True
    assert result["rule_id"] == "PY-S002"


def test_suggest_fix_endpoint_validates_length(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "max_code_chars", 10)
    resp = client.post(
        "/v1/suggest_fix",
        json={"code": "x" * 100, "language": "python"},
    )
    assert resp.status_code == 413


def test_suggest_fix_reports_llm_error(monkeypatch):
    from app import main as main_module
    from app.reviewer import ReviewError

    def fake_suggest_fix(*args, **kwargs):
        raise ReviewError("LLM API Key 未配置")

    monkeypatch.setattr(main_module, "suggest_fix_for_code", fake_suggest_fix)
    resp = client.post(
        "/v1/suggest_fix",
        json={"code": "eval(x)", "language": "python"},
    )
    assert resp.status_code == 502
    assert "LLM API Key 未配置" in resp.text


# ── Integrated review flows (mock LLM) ────────────────────────

def _mock_llm_data(monkeypatch, llm_payload: dict, issues=None):
    """Patch reviewer._call_llm to return a canned payload."""
    from app import reviewer as reviewer_module

    def fake_call(system_prompt: str, user_prompt: str) -> dict:
        data = dict(llm_payload)
        if issues is not None:
            data.setdefault("issues", issues)
        return data

    monkeypatch.setattr(reviewer_module, "_call_llm", fake_call)


def test_review_code_full_flow(monkeypatch):
    from app.reviewer import review_code

    _mock_llm_data(
        monkeypatch,
        {
            "summary": "存在安全风险。",
            "dimension_scores": {"correctness": 88, "security": 40,
                                 "performance": 90, "maintainability": 80,
                                 "best_practice": 75},
            "strengths": ["结构清晰"],
            "improvements": ["避免使用 eval"],
        },
        issues=[
            {"severity": "critical", "category": "security", "line": 1,
             "title": "eval 风险", "description": "RCE",
             "suggestion": "用 ast.literal_eval"}
        ],
    )
    report = review_code("result = eval(x)", "python", "测试")
    assert report["grade"] in ("A", "B", "C", "D")
    assert "security" in report["dimension_scores"]
    assert report["dimension_scores"]["security"] < report["dimension_scores"]["correctness"]
    assert any(i["source"] == "confirmed" for i in report["issues"])
    assert "security" in report["issues"][0]["category"]


def test_review_diff_full_flow(monkeypatch):
    from app.reviewer import review_diff

    _mock_llm_data(
        monkeypatch,
        {"summary": "diff 存在安全问题", "dimension_scores": None,
         "strengths": [], "improvements": []},
        issues=[
            {"severity": "critical", "category": "security", "line": 1,
             "title": "新增 eval", "description": "RCE", "suggestion": "不要用"}
        ],
    )
    diff = """--- a/a.py
+++ b/a.py
@@ -1,3 +1,4 @@
 def f():
-    return 1
+    return eval(data)
+    pass
"""
    result = review_diff(diff, "python")
    assert result["diff_meta"]["files_changed"] == ["a.py"]
    assert result["score"] < 90
    assert any(i["source"] in ("confirmed", "rule") for i in result["issues"])


def test_review_files_full_flow(monkeypatch):
    from app.reviewer import review_files

    _mock_llm_data(
        monkeypatch,
        {"summary": "多文件整体评审", "dimension_scores": None,
         "strengths": [], "improvements": []},
        issues=[
            {"severity": "major", "category": "security", "line": 1,
             "title": "[utils.py] 硬编码密钥", "description": "泄露风险",
             "suggestion": "用环境变量"}
        ],
    )
    files = [
        {"filename": "utils.py", "content": 'token = "sk-1234567890"', "language": "python"},
        {"filename": "main.py", "content": "import utils\nutils.main()", "language": "python"},
    ]
    result = review_files(files, "项目")
    assert "overall_report" in result
    assert len(result["file_reports"]) == 2
    assert any(i["source"] in ("rule", "confirmed") for i in result["overall_report"]["issues"])


def test_review_empty_diff_no_llm_call(monkeypatch):
    from app.reviewer import review_diff

    _mock_llm_data(
        monkeypatch,
        {"summary": "should not be called", "issues": []},
    )
    result = review_diff("--- a/x\n+++ b/x\n@@ -1 +0,0 @@\n-print(1)", "python")
    assert result["score"] == 100
    assert result["grade"] == "A"


def test_suggest_fix_full_flow(monkeypatch):
    from app.reviewer import suggest_fix_for_code

    _mock_llm_data(
        monkeypatch,
        {
            "fixed_code": "import os\napi_key = os.environ['API_KEY']",
            "explanation": "改用环境变量存储密钥。",
            "changes": ["删除硬编码", "引入 os.environ"],
        },
    )
    result = suggest_fix_for_code('api_key = "sk-1234567890"', "python")
    assert result["found_issues"] >= 1
    assert "os.environ" in result["fixed_code"]
    assert result["changes"]


def test_suggest_fix_clean_code(monkeypatch):
    from app.reviewer import suggest_fix_for_code

    _mock_llm_data(
        monkeypatch,
        {"fixed_code": None, "explanation": "empty", "changes": []},
    )
    result = suggest_fix_for_code('x = 1\nprint("hello")', "python")
    assert result["found_issues"] == 0
    assert result["fixed_code"] == 'x = 1\nprint("hello")'


# ── Brief report (MCP context saver) ─────────────────────────

def test_build_brief_report_truncates():
    from app.reviewer import _build_brief_report

    report = {
        "summary": "s", "score": 70, "grade": "C",
        "dimension_scores": {"security": 50},
        "engine_info": {"rule_count": 2},
        "strengths": ["a"], "improvements": ["b"],
        "issues": [
            {"severity": "major", "category": "security", "line": i, "title": "t",
             "description": "d" * 10, "suggestion": "s", "fix_code": "f",
             "source": "rule", "rule_id": "PY-S001", "confidence": 0.9}
            for i in range(8)
        ],
    }
    brief = _build_brief_report(report, max_issues=5)
    assert brief["issue_count"] == 8
    assert brief["truncated"] is True
    assert len(brief["issues"]) == 5
    assert "description" not in brief["issues"][0]
    assert "fix_code" not in brief["issues"][0]
    assert brief["issues"][0]["rule_id"] == "PY-S001"
    assert brief["score"] == 70
    assert brief["strengths"] == ["a"]


def test_build_brief_report_full_when_small():
    from app.reviewer import _build_brief_report

    report = {
        "summary": "s", "score": 95, "grade": "A",
        "dimension_scores": {}, "engine_info": {},
        "issues": [{"severity": "info", "category": "maintainability",
                    "line": 1, "title": "t", "source": "llm"}],
    }
    brief = _build_brief_report(report, max_issues=5)
    assert brief["truncated"] is False
    assert len(brief["issues"]) == 1


def test_mcp_review_code_detail_brief(monkeypatch):
    import json
    from app.mcp_server import review_code_tool

    _mock_llm_data(
        monkeypatch,
        {"summary": "s", "dimension_scores": None, "strengths": [], "improvements": []},
        issues=[
            {"severity": "major", "category": "security", "line": i * 10 + 1,
             "title": "t", "description": "d" * 20, "suggestion": "fix"}
            for i in range(6)
        ],
    )
    raw = review_code_tool("x = 1\nprint(x)", "python", "")
    data = json.loads(raw)
    assert data["ok"] is True
    assert data["report"]["detail"] == "brief"
    assert data["report"]["truncated"] is True
    assert len(data["report"]["issues"]) == 5


def test_mcp_review_code_detail_full(monkeypatch):
    import json
    from app.mcp_server import review_code_tool

    _mock_llm_data(
        monkeypatch,
        {"summary": "s", "dimension_scores": None, "strengths": [], "improvements": []},
        issues=[
            {"severity": "major", "category": "security", "line": 1,
             "title": "t", "description": "detailed", "suggestion": "fix",
             "fix_code": "fixed"}
        ],
    )
    raw = review_code_tool("x = 1\nprint(x)", "python", "", detail="full")
    data = json.loads(raw)
    assert data["report"]["detail"] == "full"
    assert len(data["report"]["issues"]) == 1
    assert "description" in data["report"]["issues"][0]


def test_mcp_review_files_structured_param(monkeypatch):
    import json
    from app.mcp_server import review_files_tool

    _mock_llm_data(
        monkeypatch,
        {"summary": "s", "dimension_scores": None, "strengths": [], "improvements": []},
        issues=[],
    )
    files = [
        {"filename": "a.py", "content": 'x = "sk-1234567890"', "language": "python"},
        {"filename": "b.py", "content": "print(1)", "language": "python"},
    ]
    raw = review_files_tool(files, "proj")
    data = json.loads(raw)
    assert data["ok"] is True
    assert data["result"]["file_count"] == 2
    assert data["result"]["detail"] == "brief"


# ── Diff parser ─────────────────────────────────────────────────

def test_parse_simple_diff():
    diff = """--- a/foo.py
+++ b/foo.py
@@ -1,3 +1,4 @@
 def foo():
-    return 1
+    return 2
+    pass
"""
    parsed = parse_diff(diff)
    assert "foo.py" in parsed.files_changed
    assert parsed.added_lines == 2
    assert parsed.removed_lines == 1
    assert len(parsed.hunks) == 1


def test_parse_empty_diff():
    parsed = parse_diff("")
    assert len(parsed.hunks) == 0
    assert parsed.added_lines == 0


# ── Review API ──────────────────────────────────────────────────

def test_review_requires_body():
    resp = client.post("/v1/review", json={})
    assert resp.status_code == 422


def test_review_validates_max_length(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "max_code_chars", 10)
    resp = client.post(
        "/v1/review",
        json={"code": "x" * 100, "language": "python"},
    )
    assert resp.status_code == 413


def test_review_reports_llm_error(monkeypatch):
    from app import main as main_module
    from app.reviewer import ReviewError

    def fake_review(*args, **kwargs):
        raise ReviewError("LLM API Key 未配置")

    monkeypatch.setattr(main_module, "review_code", fake_review)
    resp = client.post(
        "/v1/review",
        json={"code": "print(1)", "language": "python"},
    )
    assert resp.status_code == 502
    assert "LLM API Key 未配置" in resp.text


def test_review_diff_requires_body():
    resp = client.post("/v1/review_diff", json={})
    assert resp.status_code == 422


def test_review_files_requires_body():
    resp = client.post("/v1/review_files", json={})
    assert resp.status_code == 422


def test_review_files_rejects_empty_list():
    resp = client.post("/v1/review_files", json={"files": []})
    assert resp.status_code == 422


def test_review_files_validates_total_length(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "max_code_chars", 50)
    resp = client.post(
        "/v1/review_files",
        json={"files": [
            {"filename": "a.py", "content": "x" * 100, "language": "python"},
            {"filename": "b.py", "content": "y" * 100, "language": "python"},
        ]},
    )
    assert resp.status_code == 413


def test_review_files_reports_llm_error(monkeypatch):
    from app import main as main_module
    from app.reviewer import ReviewError

    def fake_review_files(*args, **kwargs):
        raise ReviewError("LLM API Key 未配置")

    monkeypatch.setattr(main_module, "review_files", fake_review_files)
    resp = client.post(
        "/v1/review_files",
        json={"files": [
            {"filename": "a.py", "content": "print(1)", "language": "python"},
        ]},
    )
    assert resp.status_code == 502
    assert "LLM API Key 未配置" in resp.text


# ── JSON extraction ─────────────────────────────────────────────

def test_extract_json_fenced():
    text = '```json\n{"issues": [], "score": 80, "summary": "ok"}\n```'
    data = _extract_json(text)
    assert data["score"] == 80


def test_extract_json_embedded():
    text = '说明如下：{"issues": [], "score": 90, "summary": "good"} 结束'
    data = _extract_json(text)
    assert data["score"] == 90


def test_extract_json_invalid():
    from app.reviewer import ReviewError

    with pytest.raises(ReviewError):
        _extract_json("完全没有JSON")


# ── Dimension scores ───────────────────────────────────────────

def test_dimension_scores_compute():
    from app.reviewer import _compute_dimension_scores, _compute_overall_score

    issues = [
        {"category": "security", "severity": "critical"},
        {"category": "performance", "severity": "minor"},
    ]
    scores = _compute_dimension_scores(None, issues)
    assert scores["security"] <= 50
    assert scores["performance"] < 85
    assert scores["correctness"] == 85
    overall = _compute_overall_score(scores)
    assert 0 <= overall <= 100


def test_dimension_scores_with_llm_baseline():
    from app.reviewer import _compute_dimension_scores

    llm_scores = {
        "correctness": 90,
        "security": 70,
        "performance": 85,
        "maintainability": 80,
        "best_practice": 75,
    }
    issues = [{"category": "security", "severity": "major"}]
    scores = _compute_dimension_scores(llm_scores, issues)
    assert scores["security"] == 70 - 18
    assert scores["correctness"] == 90


def test_dimension_scores_ai_pattern_affects_best_practice():
    from app.reviewer import _compute_dimension_scores

    issues = [{"category": "ai_pattern", "severity": "major"}]
    scores = _compute_dimension_scores(None, issues)
    assert scores["best_practice"] < 85
    assert scores["security"] == 85


def test_overall_score_weighted():
    from app.reviewer import _compute_overall_score

    dims = {
        "correctness": 100,
        "security": 0,
        "performance": 100,
        "maintainability": 100,
        "best_practice": 100,
    }
    score = _compute_overall_score(dims)
    assert score == 70


# ── Fix code generation ───────────────────────────────────────

def test_fix_code_eval():
    code = "result = eval(user_input)"
    findings = run_rules(code, "python")
    f = next(x for x in findings if x.rule_id == "PY-S001")
    assert f.fix_code is not None
    assert "ast.literal_eval" in f.fix_code


def test_fix_code_innerhtml():
    code = "document.getElementById('x').innerHTML = userInput"
    findings = run_rules(code, "javascript")
    f = next(x for x in findings if x.rule_id == "JS-S002")
    assert f.fix_code is not None
    assert "textContent" in f.fix_code


def test_fix_code_hardcoded_secret():
    code = 'api_key = "sk-1234567890abcdef"'
    findings = run_rules(code, "python")
    f = next(x for x in findings if x.rule_id == "PY-S004")
    assert f.fix_code is not None
    assert "os.environ" in f.fix_code


def test_fix_code_in_merge_findings():
    rule_findings = run_rules("eval('1+1')", "python")
    merged = merge_findings(rule_findings, [], "eval('1+1')")
    assert any(m.get("fix_code") for m in merged)


def test_fix_code_llm_override_on_confirm():
    rule_findings = run_rules("eval('1+1')", "python")
    llm_issues = [
        {"severity": "critical", "category": "security", "line": 1,
         "title": "eval", "description": "RCE", "suggestion": "don't use eval",
         "fix_code": "import ast\nresult = ast.literal_eval(user_input)"}
    ]
    merged = merge_findings(rule_findings, llm_issues, "eval('1+1')")
    confirmed = next(m for m in merged if m["source"] == "confirmed")
    assert confirmed["fix_code"] == "import ast\nresult = ast.literal_eval(user_input)"


# ── Rust rules ──────────────────────────────────────────────────

def test_rules_detect_rust_unsafe():
    code = "unsafe { *ptr }"
    findings = run_rules(code, "rust")
    ids = [f.rule_id for f in findings]
    assert "RS-S001" in ids


def test_rules_detect_rust_hardcoded_secret():
    code = 'let api_key = "sk-1234567890abcdef";'
    findings = run_rules(code, "rust")
    ids = [f.rule_id for f in findings]
    assert "RS-S002" in ids


def test_rules_detect_rust_unwrap():
    code = "let val = result.unwrap();"
    findings = run_rules(code, "rust")
    ids = [f.rule_id for f in findings]
    assert "RS-P001" in ids


def test_fix_code_rust_hardcoded_secret():
    code = 'let api_key = "sk-1234567890abcdef";'
    findings = run_rules(code, "rust")
    f = next(x for x in findings if x.rule_id == "RS-S002")
    assert f.fix_code is not None
    assert "std::env" in f.fix_code


def test_fix_code_rust_unwrap():
    code = "let val = result.unwrap();"
    findings = run_rules(code, "rust")
    f = next(x for x in findings if x.rule_id == "RS-P001")
    assert f.fix_code is not None
    assert "unwrap_or_default" in f.fix_code
