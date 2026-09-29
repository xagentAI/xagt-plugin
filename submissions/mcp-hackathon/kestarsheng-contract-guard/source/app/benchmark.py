# -*- coding: utf-8 -*-
"""Regression benchmark: replay the corpus through the engines and score them.

Scores precision / recall / F1 for breaking-change detection so the
"deterministic and reproducible" claim is measurable. 100% deterministic —
replaying the same corpus always yields the same score.
"""
from __future__ import annotations

from .benchmark_corpus import CORPUS
from .diff_core import DiffError, detect_changes


def _norm(x: float, default: float = 0.0) -> float:
    return round(x, 4) if x == x else default


def run_benchmark() -> dict:
    """Run every corpus sample through the diff engines and score the results."""
    tp = fp = fn = tn = 0
    results: list[dict] = []

    for name, fmt, old, new, expected in CORPUS:
        try:
            report = detect_changes(old, new, fmt)
            detected = report.breaking
        except DiffError as exc:
            detected = False
            error = str(exc)
        else:
            error = ""

        correct = (detected == expected)
        if correct and expected:
            tp += 1
        elif correct and not expected:
            tn += 1
        elif not correct and detected:
            fp += 1
        elif not correct and not detected:
            fn += 1

        results.append({
            "name": name,
            "format": fmt,
            "expected_breaking": expected,
            "detected_breaking": detected,
            "correct": correct,
            "error": error,
        })

    total = len(CORPUS)
    correct_count = tp + tn
    precision = _norm(tp / (tp + fp)) if (tp + fp) else 1.0
    recall = _norm(tp / (tp + fn)) if (tp + fn) else 1.0
    f1 = _norm(2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0

    return {
        "schema_version": 1,
        "total_samples": total,
        "correct": correct_count,
        "accuracy": round(correct_count / total, 4) if total else 1.0,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "confusion": {"tp": tp, "fp": fp, "fn": fn, "tn": tn},
        "results": results,
    }


if __name__ == "__main__":  # pragma: no cover
    import json
    print(json.dumps(run_benchmark(), indent=2, ensure_ascii=False))