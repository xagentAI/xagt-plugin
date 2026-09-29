# -*- coding: utf-8 -*-
"""Code quality metrics computation (deterministic, offline, zero LLM).

Produces a quantitative "health check" of a piece of code: size, function
length distribution, cyclomatic complexity, comment ratio, and long lines.

Python input is measured precisely with the standard-library `ast` module.
Other languages fall back to lightweight line-based heuristics.
"""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass

from .rules_engine import detect_language

_LONG_LINE_THRESHOLD = 120


@dataclass
class FunctionStat:
    name: str
    line: int
    length: int
    complexity: int


def compute_metrics(code: str, language: str = "") -> dict:
    """Compute quality metrics for a code snippet."""
    code = code or ""
    detected = detect_language(code, language)
    lines_list = code.splitlines()
    total = len(lines_list)

    code_lines = 0
    comment_lines = 0
    blank_lines = 0
    long_lines = 0

    for raw in lines_list:
        stripped = raw.strip()
        if not stripped:
            blank_lines += 1
        elif _is_comment_line(stripped):
            comment_lines += 1
        else:
            code_lines += 1
        if len(raw) > _LONG_LINE_THRESHOLD:
            long_lines += 1

    if detected == "python":
        funcs, has_syntax_error = _analyze_python_functions(code)
    else:
        funcs, has_syntax_error = _analyze_functions_heuristic(lines_list)

    if funcs:
        avg_len = round(sum(f.length for f in funcs) / len(funcs), 1)
        avg_cc = round(sum(f.complexity for f in funcs) / len(funcs), 1)
        max_len = max(f.length for f in funcs)
        max_cc = max(f.complexity for f in funcs)
    else:
        avg_len = 0.0
        avg_cc = 0.0
        max_len = 0
        max_cc = 0

    longest = sorted(funcs, key=lambda f: f.length, reverse=True)[:5]
    most_complex = sorted(funcs, key=lambda f: f.complexity, reverse=True)[:5]

    denominator = code_lines + comment_lines
    comment_ratio = round(comment_lines / denominator, 3) if denominator else 0.0

    return {
        "language": detected or language or "unknown",
        "syntax_error": has_syntax_error,
        "lines": {
            "total": total,
            "code": code_lines,
            "comment": comment_lines,
            "blank": blank_lines,
        },
        "comment_ratio": comment_ratio,
        "long_lines": long_lines,
        "functions": {
            "count": len(funcs),
            "average_length": avg_len,
            "max_length": max_len,
            "longest": [
                {"name": f.name, "line": f.line, "length": f.length}
                for f in longest
            ],
        },
        "complexity": {
            "average": avg_cc,
            "max": max_cc,
            "most_complex": [
                {"name": f.name, "line": f.line, "complexity": f.complexity}
                for f in most_complex
            ],
        },
    }


def _is_comment_line(stripped: str) -> bool:
    if stripped.startswith("#"):
        return True
    if stripped.startswith("//"):
        return True
    if stripped.startswith("/*") or stripped.startswith("*"):
        return True
    if stripped.startswith("--") or stripped.startswith("<!--"):
        return True
    return False


def _analyze_python_functions(code: str) -> tuple[list[FunctionStat], bool]:
    """Python: precise AST-based function length + cyclomatic complexity."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return [], True

    funcs: list[FunctionStat] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        length = (node.end_lineno or node.lineno) - node.lineno + 1
        funcs.append(FunctionStat(
            name=node.name,
            line=node.lineno,
            length=length,
            complexity=_cyclomatic_complexity(node),
        ))
    return funcs, False


def _cyclomatic_complexity(node: ast.AST) -> int:
    """McCabe cyclomatic complexity: 1 + number of decision points."""

    def decisions(n: ast.AST) -> int:
        count = 0
        for child in ast.walk(n):
            if isinstance(child, (ast.If, ast.While, ast.For, ast.AsyncFor,
                                  ast.ExceptHandler, ast.With, ast.AsyncWith,
                                  ast.Assert, ast.Raise)):
                count += 1
            elif isinstance(child, ast.BoolOp):
                count += len(child.values) - 1
        return count

    return 1 + decisions(node)


def _analyze_functions_heuristic(lines: list[str]) -> tuple[list[FunctionStat], bool]:
    """Non-Python fallback: rough visual-structure function detection.

    We detect function-like opening lines (def / function / fn / func / public
    static ... () {) and take a best-effort body length from indentation.
    """
    opening = re.compile(
        r"^\s*(?:def|function|fn|func|public|private|protected|static|export)?"
        r"\s*\w+\s*\([^)]*\)\s*(?::|\{|=>)?\s*(?:#|//)?",
    )
    funcs: list[FunctionStat] = []
    i = 0
    total = len(lines)
    while i < total:
        line = lines[i]
        if opening.match(line) and "(" in line and ")" in line:
            start = i + 1
            name_match = re.search(r"\b(\w+)\s*\(", line)
            name = name_match.group(1) if name_match else "<anonymous>"
            body_indent = _body_indent(lines, i)
            j = i + 1
            if body_indent is None:
                end = min(total - 1, i + 2)
            else:
                while j < total:
                    nxt = lines[j]
                    if nxt.strip() and (not nxt.startswith(" ") and not nxt.startswith("\t")):
                        break
                    if body_indent and not _has_indent(nxt, body_indent) and nxt.strip():
                        break
                    j += 1
                end = min(total - 1, j - 1 if j > i + 1 else i)
            funcs.append(FunctionStat(
                name=name,
                line=start,
                length=end - start + 1,
                complexity=1 + _rough_decision_points(lines[start:end + 1]),
            ))
            i = end + 1
        else:
            i += 1
    return funcs, False


def _body_indent(lines: list[str], start: int) -> str | None:
    if start + 1 >= len(lines):
        return None
    for line in lines[start + 1:]:
        if line.strip():
            m = re.match(r"^(\s+)", line)
            return m.group(1) if m else ""
    return None


def _has_indent(line: str, indent: str) -> bool:
    return line.startswith(indent) or not line.strip()


def _rough_decision_points(lines: list[str]) -> int:
    count = 0
    for line in lines:
        stripped = line.strip()
        for token in ("if ", "for ", "while ", "switch", "case ", "catch", "&&", "||"):
            if token in stripped:
                count += 1
    return count