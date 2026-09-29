# -*- coding: utf-8 -*-
"""Unified diff parser for diff-level code review.

Parses standard unified diff format (git diff, GitHub PR diff) and
extracts changed lines with context for targeted review.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class DiffHunk:
    """A single hunk within a diff."""
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    file_path: str
    lines: list[tuple[str, str, int]]  # (sign, content, new_line_number)


@dataclass
class ParsedDiff:
    """Result of parsing a unified diff."""
    hunks: list[DiffHunk]
    files_changed: list[str]
    added_lines: int
    removed_lines: int
    reconstructed_code: str  # changed lines joined for review


_HUNK_HEADER = re.compile(
    r"^@@\s+-(\d+)(?:,(\d+))?\s+\+(\d+)(?:,(\d+))?\s+@@"
)
_FILE_HEADER = re.compile(r"^\+\+\+\s+(?:b/)?(.+)$")


def parse_diff(diff_text: str) -> ParsedDiff:
    """Parse a unified diff string into structured hunks."""
    hunks: list[DiffHunk] = []
    files_changed: set[str] = set()
    added = 0
    removed = 0

    lines = diff_text.splitlines()
    i = 0
    current_file = ""
    reconstructed_parts: list[str] = []

    while i < len(lines):
        line = lines[i]

        file_match = _FILE_HEADER.match(line)
        if file_match:
            current_file = file_match.group(1)
            files_changed.add(current_file)
            i += 1
            continue

        hunk_match = _HUNK_HEADER.match(line)
        if hunk_match:
            old_start = int(hunk_match.group(1))
            old_count = int(hunk_match.group(2) or 1)
            new_start = int(hunk_match.group(3))
            new_count = int(hunk_match.group(4) or 1)

            hunk_lines: list[tuple[str, str, int]] = []
            new_line_num = new_start
            i += 1

            while i < len(lines):
                hl = lines[i]
                if hl.startswith("@@") or hl.startswith("+++") or hl.startswith("---"):
                    break

                if hl.startswith("+"):
                    hunk_lines.append(("+", hl[1:], new_line_num))
                    reconstructed_parts.append(hl[1:])
                    new_line_num += 1
                    added += 1
                elif hl.startswith("-"):
                    hunk_lines.append(("-", hl[1:], 0))
                    removed += 1
                elif hl.startswith(" "):
                    hunk_lines.append((" ", hl[1:], new_line_num))
                    new_line_num += 1
                elif hl == "":
                    pass
                i += 1

            hunks.append(DiffHunk(
                old_start=old_start, old_count=old_count,
                new_start=new_start, new_count=new_count,
                file_path=current_file,
                lines=hunk_lines,
            ))
            continue

        i += 1

    reconstructed_code = "\n".join(reconstructed_parts)
    return ParsedDiff(
        hunks=hunks,
        files_changed=sorted(files_changed),
        added_lines=added,
        removed_lines=removed,
        reconstructed_code=reconstructed_code,
    )


def diff_summary(parsed: ParsedDiff) -> str:
    """Generate a human-readable summary of the diff."""
    parts = [
        f"变更文件: {', '.join(parsed.files_changed) or '未知'}",
        f"新增 {parsed.added_lines} 行, 删除 {parsed.removed_lines} 行",
        f"共 {len(parsed.hunks)} 个 hunk",
    ]
    return " | ".join(parts)