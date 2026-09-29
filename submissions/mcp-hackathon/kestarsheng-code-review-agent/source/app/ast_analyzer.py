# -*- coding: utf-8 -*-
"""AST-level static analysis engine (Python).

Unlike the regex rule engine, this parses source with the standard-library
`ast` module and reasons about the actual syntax tree. It detects issues the
regex engine cannot see reliably:

- PY-AST-S001  SyntaxError: the code does not even parse
- PY-AST-I001  unused import
- PY-AST-U001  reference to a variable that is not defined in scope
- PY-AST-D001  duplicate function/class definition (later wins, silent bug)
- PY-AST-M001  function body that only contains `pass` (unimplemented stub)

All checks are deterministic, offline, and cost zero LLM tokens.
"""
from __future__ import annotations

import ast
import builtins

from .rules_engine import Finding

_BUILTIN_NAMES = set(dir(builtins))
_SKIP_NAMES = {
    "__name__", "__file__", "__doc__", "__package__", "__loader__",
    "__spec__", "__builtins__", "__main__", "self", "cls",
}


def analyze_python(code: str) -> list[Finding]:
    """Run AST-level analysis on Python source, returning deterministic findings."""
    try:
        tree = ast.parse(code)
    except (SyntaxError, ValueError) as exc:
        lineno = getattr(exc, "lineno", None) or 1
        msg = getattr(exc, "msg", "unknown syntax error") or "unknown syntax error"
        return [
            Finding(
                rule_id="PY-AST-S001",
                severity="critical",
                category="correctness",
                line=lineno,
                title="Python 语法错误，代码无法解析",
                description=f"第 {lineno} 行存在语法错误: {msg}。代码无法被执行，所有下游分析均已停止。",
                suggestion="修复语法后才能继续评审。检查括号/引号/缩进是否配对，并用编辑器语法高亮定位错误行。",
                confidence=1.0,
                source="ast",
            )
        ]

    findings: list[Finding] = []
    findings.extend(_find_unused_imports(tree, code))
    findings.extend(_find_undefined_names(tree))
    findings.extend(_find_duplicate_definitions(tree))
    findings.extend(_find_empty_functions(tree))
    return findings


def _name_targets(node: ast.AST) -> set[str]:
    """Collect names assigned by a target node (handles Tuple/List unpacking)."""
    if isinstance(node, ast.Name):
        return {node.id}
    if isinstance(node, (ast.Tuple, ast.List)):
        names: set[str] = set()
        for elt in node.elts:
            names |= _name_targets(elt)
        return names
    if isinstance(node, ast.Starred):
        return _name_targets(node.value)
    return set()


def _find_unused_imports(tree: ast.AST, code: str) -> list[Finding]:
    """Flag imports whose names never appear outside their own import statement."""
    findings: list[Finding] = []
    lines = code.splitlines()

    for node in ast.walk(tree):
        if not isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        for alias in node.names:
            name = alias.asname or alias.name.split(".")[0]
            if name == "*":
                continue
            within = 0
            for lineno in range(node.lineno, (node.end_lineno or node.lineno) + 1):
                if lineno <= len(lines):
                    within += lines[lineno - 1].count(name)
            total = code.count(name)
            if total <= within:
                findings.append(Finding(
                    rule_id="PY-AST-I001",
                    severity="minor",
                    category="maintainability",
                    line=node.lineno,
                    title=f"未使用的 import: {alias.name}",
                    description=f"import '{alias.name}' 在代码中从未被使用，属于冗余代码，会增加理解成本。",
                    suggestion="删除该 import 语句。如果它只是为副作用引入的（如注册插件），显式用下划线标注或以注释说明。",
                    confidence=0.85,
                    source="ast",
                ))
    return findings


def _collect_defined_names(tree: ast.AST) -> set[str]:
    """Collect every name that is definitely defined somewhere in the module."""
    defined: set[str] = set(_BUILTIN_NAMES) | _SKIP_NAMES

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = node.args
            for a in list(args.posonlyargs) + list(args.args) + list(args.kwonlyargs):
                defined.add(a.arg)
            if args.vararg:
                defined.add(args.vararg.arg)
            if args.kwarg:
                defined.add(args.kwarg.arg)
        elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            if isinstance(node, ast.Assign):
                targets = node.targets
            else:
                targets = [node.target]
            for t in targets:
                defined |= _name_targets(t)
        elif isinstance(node, (ast.For, ast.AsyncFor)):
            defined |= _name_targets(node.target)
        elif isinstance(node, (ast.With, ast.AsyncWith)):
            for item in node.items:
                if item.optional_vars is not None:
                    defined |= _name_targets(item.optional_vars)
        elif isinstance(node, ast.ExceptHandler):
            if node.name:
                defined.add(node.name)
        elif isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            for gen in node.generators:
                defined |= _name_targets(gen.target)
    return defined


def _find_undefined_names(tree: ast.AST) -> list[Finding]:
    """Flag Load-context names inside functions that are never defined.

    Only function bodies are inspected: at module top level we cannot know
    whether a name comes from an external package, so we stay conservative
    and keep confidence low to avoid false positives.
    """
    defined = _collect_defined_names(tree)
    findings: list[Finding] = []
    seen: set[tuple[int, str]] = set()

    def visit(node: ast.AST, in_function: bool) -> None:
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            if in_function and node.id not in defined:
                key = (node.lineno, node.id)
                if key not in seen:
                    seen.add(key)
                    findings.append(Finding(
                        rule_id="PY-AST-U001",
                        severity="major",
                        category="correctness",
                        line=node.lineno,
                        title=f"可能引用了未定义的变量: {node.id}",
                        description=(
                            f"变量 '{node.id}' 在当前作用域中未找到赋值、参数或 import 来源，"
                            f"运行时可能抛出 NameError。"
                        ),
                        suggestion=(
                            "确认该变量已赋值、已作为参数传入，或补充 import。"
                            "若依赖外部全局变量，请显式传入或用注释说明。"
                        ),
                        confidence=0.65,
                        source="ast",
                    ))
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for child in ast.iter_child_nodes(node):
                visit(child, True)
            return
        for child in ast.iter_child_nodes(node):
            visit(child, in_function)

    for stmt in tree.body:
        visit(stmt, False)
    return findings


def _find_duplicate_definitions(tree: ast.AST) -> list[Finding]:
    """Flag two same-named function/class definitions in the same scope."""
    findings: list[Finding] = []

    def scan_body(body: list[ast.stmt]) -> None:
        seen: dict[str, int] = {}
        for stmt in body:
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if stmt.name in seen:
                    findings.append(Finding(
                        rule_id="PY-AST-D001",
                        severity="major",
                        category="correctness",
                        line=stmt.lineno,
                        title=f"重复定义: {stmt.name}",
                        description=(
                            f"'{stmt.name}' 已在第 {seen[stmt.name]} 行定义过，当前定义会静默覆盖前者，"
                            f"这在条件分支或后续调用时会产生难以排查的 bug。"
                        ),
                        suggestion="合并重复定义或重命名，确保同作用域内名称唯一。",
                        confidence=0.9,
                        source="ast",
                    ))
                else:
                    seen[stmt.name] = stmt.lineno

            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                scan_body(stmt.body)
            elif isinstance(stmt, (ast.If,)):
                scan_body(stmt.body)
                scan_body(stmt.orelse)
            elif isinstance(stmt, (ast.For, ast.AsyncFor, ast.While)):
                scan_body(stmt.body)
                scan_body(stmt.orelse)
            elif isinstance(stmt, (ast.With, ast.AsyncWith)):
                scan_body(stmt.body)
            elif isinstance(stmt, ast.Try):
                scan_body(stmt.body)
                for handler in stmt.handlers:
                    scan_body(handler.body)
                scan_body(stmt.orelse)
                scan_body(stmt.finalbody)

    scan_body(tree.body)
    return findings


def _find_empty_functions(tree: ast.AST) -> list[Finding]:
    """Flag functions whose body is only `pass` (unimplemented stubs)."""
    findings: list[Finding] = []

    def _is_empty(body: list[ast.stmt]) -> bool:
        non_doc = [
            n for n in body
            if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)
                    and isinstance(n.value.value, str))
        ]
        return non_doc and all(isinstance(n, ast.Pass) for n in non_doc)

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and _is_empty(node.body):
            findings.append(Finding(
                rule_id="PY-AST-M001",
                severity="info",
                category="maintainability",
                line=node.lineno,
                title=f"函数体仅为 pass 占位: {node.name}",
                description=f"'{node.name}' 尚未实现，仅以 pass 占位，调用时会得到 None 而非预期结果。",
                suggestion="实现函数逻辑，或改为抛出 NotImplementedError 以显式标记未完成。",
                confidence=0.75,
                source="ast",
            ))
    return findings