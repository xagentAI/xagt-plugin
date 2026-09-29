# -*- coding: utf-8 -*-
"""Unit tests for the built-in regression benchmark."""
from app.benchmark import run_benchmark
from app.benchmark_corpus import CORPUS


def test_corpus_has_enough_samples():
    assert len(CORPUS) >= 16


def test_corpus_covers_three_formats():
    formats = {sample[1] for sample in CORPUS}
    assert formats == {"openapi", "graphql", "json-schema"}


def test_benchmark_runs_and_scores():
    b = run_benchmark()
    assert b["total_samples"] == len(CORPUS)
    assert b["correct"] == b["total_samples"]
    assert b["accuracy"] == 1.0
    assert b["precision"] == 1.0
    assert b["recall"] == 1.0
    assert b["f1"] == 1.0
    assert b["confusion"] == {"tp": 11, "fp": 0, "fn": 0, "tn": 5}


def test_benchmark_is_reproducible():
    b1 = run_benchmark()
    b2 = run_benchmark()
    assert b1["f1"] == b2["f1"]
    assert [r["name"] for r in b1["results"]] == [r["name"] for r in b2["results"]]


def test_benchmark_every_sample_correct():
    b = run_benchmark()
    bad = [r["name"] for r in b["results"] if not r["correct"]]
    assert bad == [], f"Incorrect samples: {bad}"


def test_benchmark_exposes_labels_for_verification():
    b = run_benchmark()
    result = b["results"][0]
    assert {"name", "format", "expected_breaking", "detected_breaking", "correct"} <= set(result)