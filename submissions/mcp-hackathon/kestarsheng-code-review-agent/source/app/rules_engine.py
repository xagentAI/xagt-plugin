# -*- coding: utf-8 -*-
"""Rule-based code analysis engine.

Detects known anti-patterns, security risks, and AI-generated code
hallucinations through static pattern matching — no LLM required.

Each rule has:
- id: stable identifier (e.g. PY-S001)
- language: target language (* = all)
- severity: critical / major / minor / info
- category: security / performance / maintainability / best_practice / ai_pattern
- pattern: compiled regex
- confidence: 0.0-1.0 (how likely this is a real issue)
- title / description / suggestion: human-readable guidance
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Sequence

@dataclass(frozen=True)
class Rule:
    id: str
    language: str
    severity: str
    category: str
    pattern: re.Pattern
    confidence: float
    title: str
    description: str
    suggestion: str

@dataclass
class Finding:
    rule_id: str
    severity: str
    category: str
    line: int
    title: str
    description: str
    suggestion: str
    confidence: float
    source: str = "rule"
    fix_code: str | None = None

def _r(rule_id, lang, sev, cat, pat, conf, title, desc, sug):
    return Rule(rule_id, lang, sev, cat, re.compile(pat, re.MULTILINE), conf, title, desc, sug)

RULES: list[Rule] = [

    # ── Python: Security ──────────────────────────────────────────
    _r("PY-S001", "python", "critical", "security",
       r"\beval\s*\(", 0.95,
       "使用 eval() 执行任意代码",
       "eval() 会执行任意字符串作为代码，是严重的注入风险点。攻击者可通过构造恶意输入实现 RCE。",
       "避免使用 eval()。如需解析表达式，使用 ast.literal_eval() 或专用解析器。"),

    _r("PY-S002", "python", "critical", "security",
       r"\bexec\s*\(", 0.95,
       "使用 exec() 执行任意代码",
       "exec() 与 eval() 同样危险，可执行任意代码字符串，存在注入风险。",
       "重构代码避免动态执行。如必须使用，确保输入经过严格沙箱过滤。"),

    _r("PY-S003", "python", "critical", "security",
       r"(?:os\.system|subprocess\.call|subprocess\.run)\s*\(\s*['\"].*%s|"
       r"(?:os\.system|subprocess\.(?:call|run|Popen))\s*\([^)]*shell\s*=\s*True",
       0.85,
       "命令注入风险：shell=True 或字符串拼接执行系统命令",
       "使用 shell=True 或字符串拼接构造命令时，攻击者可注入恶意命令参数。",
       "使用 subprocess 并传入列表参数，设置 shell=False：\n"
       "subprocess.run(['ls', user_input], shell=False)"),

    _r("PY-S004", "python", "major", "security",
       r"(?:password|passwd|secret|api_key|token)\s*=\s*['\"][^'\"]{6,}['\"]",
       0.80,
       "硬编码密钥/密码",
       "代码中直接硬编码了密码、API Key 或 Token，泄露后可被直接利用。",
       "使用环境变量或密钥管理服务：\n"
       "api_key = os.environ['API_KEY']"),

    _r("PY-S005", "python", "major", "security",
       r"pickle\.loads?\s*\(",
       0.90,
       "使用 pickle 反序列化不可信数据",
       "pickle.loads() 可执行任意代码，反序列化不可信数据等同于 RCE 漏洞。",
       "使用 JSON 等安全格式序列化数据，或 jsonpickle 并限制类白名单。"),

    _r("PY-S006", "python", "major", "security",
       r"\.execute\s*\([^)]*%[^)]|\.execute\s*\([^)]*\+|"
       r"cursor\.execute\s*\(\s*f['\"]",
       0.85,
       "SQL 注入风险：字符串拼接/f-string 构造 SQL",
       "直接拼接变量到 SQL 语句中，攻击者可注入恶意 SQL 片段。",
       "使用参数化查询：\n"
       "cursor.execute('SELECT * FROM users WHERE id = %s', (user_id,))"),

    # ── Python: Performance ───────────────────────────────────────
    _r("PY-P001", "python", "major", "performance",
       r"for\s+\w+\s+in\s+.*:\s*\n\s*for\s+\w+\s+in\s+.*:",
       0.70,
       "嵌套循环可能导致 O(n²) 性能问题",
       "双层嵌套循环在数据量大时性能急剧下降。",
       "考虑使用集合/字典查找、itertools 或算法优化降低时间复杂度。"),

    _r("PY-P002", "python", "minor", "performance",
       r"\.items\s*\(\)\s*\n\s*\w+\s*=\s*\w+\[0\]|\bfor\s+\w+\s+in\s+\w+\.keys\s*\(\):",
       0.60,
       "遍历字典时未使用 .items() 导致多次查找",
       "先遍历 keys 再用 dict[key] 访问值，每次查找都是 O(1) 但常数项大。",
       "使用 for k, v in d.items() 一次获取键值。"),

    _r("PY-P003", "python", "minor", "performance",
       r"list\s*\(\s*range\s*\(\s*\d{4,}\s*\)\s*\)",
       0.65,
       "预生成大范围列表浪费内存",
       "list(range(10000)) 会一次性分配所有元素内存。",
       "直接使用 range() 迭代器，惰性求值节省内存。"),

    # ── Python: Best Practice ─────────────────────────────────────
    _r("PY-B001", "python", "minor", "best_practice",
       r"^\s*except\s*:|^\s*except\s+Exception\s*:",
       0.50,
       "过宽的异常捕获",
       "裸 except 或 except Exception 会吞掉所有异常，包括 KeyboardInterrupt、SystemExit。",
       "捕获具体异常类型：\nexcept (ValueError, TypeError) as e:"),

    _r("PY-B002", "python", "info", "best_practice",
       r"^\s*def\s+\w+\s*\([^)]*\)\s*:",
       0.40,
       "函数缺少类型注解",
       "无类型注解的函数可读性和可维护性较差，IDE 无法提供准确提示。",
       "添加类型注解：\ndef add(a: int, b: int) -> int:"),

    # ── JavaScript: Security ──────────────────────────────────────
    _r("JS-S001", "javascript", "critical", "security",
       r"\beval\s*\(",
       0.95,
       "使用 eval() 执行任意代码",
       "JavaScript 中 eval() 执行任意字符串，是 XSS 和代码注入的主要入口。",
       "使用 JSON.parse() 解析数据，或 Function 构造器配合严格输入验证。"),

    _r("JS-S002", "javascript", "critical", "security",
       r"innerHTML\s*[=+]|document\.write\s*\(",
       0.85,
       "innerHTML/document.write 导致 XSS",
       "直接写入 innerHTML 或使用 document.write 会将字符串解析为 HTML，可注入恶意脚本。",
       "使用 textContent 或 DOM API 创建元素：\n"
       "el.textContent = userInput;"),

    _r("JS-S003", "javascript", "major", "security",
       r"(?:password|secret|apiKey|token)\s*[:=]\s*['\"][^'\"]{6,}['\"]",
       0.80,
       "硬编码密钥/Token",
       "前端代码中的密钥可被任何用户查看，后端密钥泄露后可被直接利用。",
       "使用环境变量（后端）或安全的配置服务，前端不存储敏感密钥。"),

    # ── JavaScript: AI Pattern ────────────────────────────────────
    _r("JS-A001", "javascript", "major", "ai_pattern",
       r"import\s+.*\s+from\s+['\"](?:lodash-es|underscore)['\"]\s*;",
       0.55,
       "AI 生成代码常见模式：全量导入 lodash",
       "AI 常生成 import _ from 'lodash' 全量导入，现代前端应按需导入。",
       "按需导入：import debounce from 'lodash/debounce'"),

    # ── Java: Security ────────────────────────────────────────────
    _r("JV-S001", "java", "critical", "security",
       r"Runtime\.getRuntime\s*\(\s*\)\.exec\s*\(",
       0.90,
       "使用 Runtime.exec() 执行命令",
       "Runtime.exec() 若拼接用户输入可导致命令注入。",
       "使用 ProcessBuilder 并传入参数列表，避免 shell 解释。"),

    _r("JV-S002", "java", "major", "security",
       r"Statement\s+\w+\s*=.*\n.*\.execute\s*\(\s*['\"]\s*\+|"
       r"createStatement\s*\(\s*\).*\n.*\.execute\s*\(\s*['\"]\s*\+",
       0.80,
       "SQL 注入：Statement 拼接 SQL",
       "使用 Statement 拼接 SQL 字符串存在注入风险。",
       "使用 PreparedStatement 参数化查询：\n"
       "ps = conn.prepareStatement(sql); ps.setString(1, input);"),

    # ── Go: Security ──────────────────────────────────────────────
    _r("GO-S001", "go", "major", "security",
       r"os\.Exec\s*\(",
       0.85,
       "使用 os.Exec 执行外部命令",
       "os.Exec 已被废弃，且拼接用户输入存在命令注入风险。",
       "使用 exec.Command 并传入参数列表：\n"
       "cmd := exec.Command('ls', arg)"),

    # ── Rust: Security & Reliability ──────────────────────────────
    _r("RS-S001", "rust", "critical", "security",
       r"\bunsafe\s*\{",
       0.90,
       "使用 unsafe 块",
       "unsafe 块绕过了 Rust 的内存安全保证，可能导致未定义行为、内存泄漏或段错误。",
       "审查 unsafe 块的必要性，尽量用安全 API 替代。若必须使用，添加 SAFETY 注释说明不变量。"),

    _r("RS-S002", "rust", "major", "security",
       r"(?:let\s+)?(?:const\s+)?(?:static\s+)?\w*\s*(?::\s*\w+\s*)?=\s*['\"](?:password|passwd|secret|api_key|token|sk-)[^'\"]*['\"]",
       0.80,
       "硬编码密钥或密码",
       "将密钥硬编码在源码中，泄露风险极高。",
       "使用环境变量或配置文件：\n"
       "std::env::var(\"API_KEY\").expect(\"API_KEY not set\")"),

    _r("RS-P001", "rust", "major", "performance",
       r"\.unwrap\s*\(\s*\)",
       0.75,
       "使用 .unwrap() 可能导致 panic",
       ".unwrap() 在 None/Err 时会 panic，生产代码中应避免。",
       "使用 match 或 if let 处理错误：\n"
       "match result { Ok(v) => v, Err(e) => return Err(e.into()) }"),

    _r("RS-S003", "rust", "major", "security",
       r"Command::new\s*\([^)]*\)\s*\.arg\s*\(\s*(?:format!|&)?",
       0.70,
       "Command::new 拼接用户输入存在命令注入风险",
       "若 arg 内容来自用户输入且未做校验，可能被注入恶意参数。",
       "对用户输入做严格校验，或使用 .args() 传入固定参数列表。"),

    # ── Cross-language: AI Hallucination Patterns ─────────────────
    _r("AI-H001", "*", "major", "ai_pattern",
       r"(?:import|from|require)\s+['\"](?:react|vue|angular|svelte|next|nuxt)/"
       r"(?:utils|helpers|common|shared)['\"]",
       0.45,
       "可能引用了不存在的框架内部模块",
       "AI 常臆造框架内部工具模块路径（如 react/utils），这些路径通常不存在。",
       "检查该模块是否真实存在，使用框架官方文档确认正确导入路径。"),

    _r("AI-H002", "*", "minor", "ai_pattern",
       r"(?:\.|->)\s*(?:forEach|map|filter|reduce)\s*\(\s*(?:async\s+)?\([^)]*\)\s*=>\s*\{[^}]*await\s+",
       0.55,
       "在 forEach/map 中使用 await",
       "Array.forEach 不等待 Promise，在回调中使用 await 会导致并发问题。map+await 同理。",
       "使用 for...of 循环或 Promise.all：\n"
       "await Promise.all(items.map(async fn))"),

    _r("AI-H003", "*", "major", "ai_pattern",
       r"try\s*\{[^}]*\}\s*catch\s*\([^)]*\)\s*\{\s*(?:console\.log|print|System\.out)\s*\([^)]*\)\s*;?\s*\}",
       0.60,
       "catch 块仅打印日志未处理异常",
       "AI 常生成 catch (e) { console.log(e) } 模式，异常被吞掉且未上报。",
       "至少应重新抛出或返回错误：\n"
       "catch (e) { logger.error(e); throw e; }"),

    # ── Cross-language: Maintainability ───────────────────────────
    _r("X-M001", "*", "info", "maintainability",
       r"(?:TODO|FIXME|HACK|XXX)\b",
       0.90,
       "代码中存在 TODO/FIXME 标记",
       "未完成的技术债务标记，应在发布前处理或转为 Issue 跟踪。",
       "将 TODO 转为 Issue 跟踪，或在发布前完成修复。"),
]

def detect_language(code: str, hint: str = "") -> str:
    """Detect programming language from hint or code content."""
    hint = hint.lower().strip()
    mapping = {
        "py": "python", "python": "python", "python3": "python",
        "js": "javascript", "javascript": "javascript", "jsx": "javascript",
        "ts": "javascript", "typescript": "javascript", "tsx": "javascript",
        "java": "java", "jsp": "java",
        "go": "go", "golang": "go",
        "c": "c", "cpp": "c", "c++": "c", "h": "c",
        "rs": "rust", "rust": "rust",
        "rb": "ruby", "ruby": "ruby",
        "php": "php",
        "sh": "shell", "bash": "shell", "shell": "shell",
    }
    if hint in mapping:
        return mapping[hint]

    indicators = [
        (r"\bdef\s+\w+\s*\(", "python"),
        (r"\bimport\s+java\.", "java"),
        (r"\bpackage\s+\w+\s+import\s+", "go"),
        (r"\bfunc\s+\w+\s*\(", "go"),
        (r"\b(?:const|let|var)\s+\w+\s*=", "javascript"),
        (r"\bfn\s+\w+\s*\(", "rust"),
        (r"\bdef\s+\w+\s*$", "ruby"),
        (r"<\?php", "php"),
        (r"#!/bin/(?:ba)?sh", "shell"),
    ]
    for pattern, lang in indicators:
        if re.search(pattern, code):
            return lang
    return ""

def _line_number(code: str, pos: int) -> int:
    return code.count("\n", 0, pos) + 1


def _extract_line(code: str, pos: int) -> str:
    """Extract the full line containing the given position."""
    start = code.rfind("\n", 0, pos) + 1
    end = code.find("\n", pos)
    if end == -1:
        end = len(code)
    return code[start:end]


_FIX_GENERATORS: dict[str, callable] = {}


def _fix_gen(rule_id: str):
    """Decorator to register a fix code generator for a rule."""
    def decorator(fn):
        _FIX_GENERATORS[rule_id] = fn
        return fn
    return decorator


@_fix_gen("PY-S001")
def _fix_eval(match_text: str, full_line: str) -> str:
    return full_line.replace("eval(", "ast.literal_eval(")


@_fix_gen("PY-S002")
def _fix_exec(match_text: str, full_line: str) -> str:
    indent = full_line[: len(full_line) - len(full_line.lstrip())]
    return f"{indent}# 重构：避免使用 exec()，改为安全的实现方式"


@_fix_gen("PY-S004")
def _fix_hardcoded_secret(match_text: str, full_line: str) -> str:
    indent = full_line[: len(full_line) - len(full_line.lstrip())]
    var_match = re.match(r"\s*(\w+)\s*=\s*['\"]", full_line)
    var_name = var_match.group(1).upper() if var_match else "SECRET"
    return f"{indent}{var_match.group(1) if var_match else 'secret'} = os.environ['{var_name}']"


@_fix_gen("PY-S006")
def _fix_sql_injection(match_text: str, full_line: str) -> str:
    indent = full_line[: len(full_line) - len(full_line.lstrip())]
    return f"{indent}# 使用参数化查询：cursor.execute(sql, (param,))"


@_fix_gen("JS-S001")
def _fix_js_eval(match_text: str, full_line: str) -> str:
    return full_line.replace("eval(", "JSON.parse(")


@_fix_gen("JS-S002")
def _fix_innerhtml(match_text: str, full_line: str) -> str:
    return full_line.replace("innerHTML", "textContent")


@_fix_gen("PY-B001")
def _fix_bare_except(match_text: str, full_line: str) -> str:
    return full_line.replace("except:", "except (ValueError, TypeError) as e:")


@_fix_gen("AI-H003")
def _fix_swallowed_catch(match_text: str, full_line: str) -> str:
    indent = full_line[: len(full_line) - len(full_line.lstrip())]
    return f"{indent}catch (e) {{ logger.error(e); throw e; }}"


@_fix_gen("RS-S002")
def _fix_rust_hardcoded_secret(match_text: str, full_line: str) -> str:
    indent = full_line[: len(full_line) - len(full_line.lstrip())]
    var_match = re.match(r"\s*(?:let\s+)?(?:const\s+)?(?:static\s+)?(\w+)", full_line)
    var_name = var_match.group(1).upper() if var_match else "SECRET"
    return f"{indent}std::env::var(\"{var_name}\").expect(\"{var_name} not set\")"


@_fix_gen("RS-P001")
def _fix_rust_unwrap(match_text: str, full_line: str) -> str:
    return full_line.replace(".unwrap()", ".unwrap_or_default()")

def run_rules(code: str, language: str = "") -> list[Finding]:
    """Run all applicable rules against the code and return findings."""
    detected = detect_language(code, language)

    findings: list[Finding] = []
    for rule in RULES:
        if rule.language != "*" and rule.language != detected:
            continue
        for match in rule.pattern.finditer(code):
            fix_code = None
            generator = _FIX_GENERATORS.get(rule.id)
            if generator:
                try:
                    full_line = _extract_line(code, match.start())
                    fix_code = generator(match.group(0), full_line)
                except Exception:
                    fix_code = None
            findings.append(Finding(
                rule_id=rule.id,
                severity=rule.severity,
                category=rule.category,
                line=_line_number(code, match.start()),
                title=rule.title,
                description=rule.description,
                suggestion=rule.suggestion,
                confidence=rule.confidence,
                source="rule",
                fix_code=fix_code,
            ))
    return findings

def merge_findings(
    rule_findings: list[Finding],
    llm_issues: list[dict],
    code: str,
) -> list[dict]:
    """Merge rule-based findings with LLM-detected issues.

    Strategy:
    - Rule findings with confidence >= 0.8 are kept as-is (high trust)
    - Rule findings with confidence < 0.8 are marked for LLM confirmation
    - LLM issues that overlap with rule findings are upgraded (confirmed)
    - LLM-only issues are kept with source="llm"
    - Deduplicate by (line, category) proximity
    """
    merged: list[dict] = []
    seen_positions: set[tuple[str, int]] = set()

    for f in rule_findings:
        key = (f.category, f.line)
        if key in seen_positions:
            continue
        seen_positions.add(key)
        merged.append({
            "severity": f.severity,
            "category": f.category,
            "line": f.line,
            "title": f.title,
            "description": f.description,
            "suggestion": f.suggestion,
            "fix_code": f.fix_code,
            "source": "rule",
            "rule_id": f.rule_id,
            "confidence": f.confidence,
        })

    for issue in llm_issues:
        line = issue.get("line")
        cat = issue.get("category", "")
        key = (cat, line or 0)

        overlap = any(
            abs((m.get("line") or 0) - (line or 0)) <= 2
            and m.get("category") == cat
            for m in merged
        )

        if overlap:
            for m in merged:
                if (abs((m.get("line") or 0) - (line or 0)) <= 2
                        and m.get("category") == cat):
                    m["source"] = "confirmed"
                    m["confidence"] = min(1.0, m.get("confidence", 0.5) + 0.3)
                    if not m.get("description") and issue.get("description"):
                        m["description"] = issue["description"]
                    if issue.get("fix_code"):
                        m["fix_code"] = issue["fix_code"]
                    break
        else:
            merged.append({
                "severity": issue.get("severity", "info"),
                "category": cat,
                "line": line,
                "title": issue.get("title", ""),
                "description": issue.get("description", ""),
                "suggestion": issue.get("suggestion", ""),
                "fix_code": issue.get("fix_code"),
                "source": "llm",
                "rule_id": None,
                "confidence": 0.7,
            })

    severity_order = {"critical": 0, "major": 1, "minor": 2, "info": 3}
    merged.sort(key=lambda x: (severity_order.get(x["severity"], 9), x.get("line") or 0))
    return merged