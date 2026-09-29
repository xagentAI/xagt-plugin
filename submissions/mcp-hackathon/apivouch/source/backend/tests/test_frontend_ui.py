"""Focused static contracts for the dependency-free product workbench."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INDEX = (ROOT / "frontend/index.html").read_text(encoding="utf-8")
APP = (ROOT / "frontend/app.js").read_text(encoding="utf-8")


def test_mobile_outcome_layout_stacks_without_hiding_overflow():
    assert ".outcome-metrics,.attempts{grid-template-columns:minmax(0,1fr)}" in INDEX
    assert "overflow-wrap:anywhere" in INDEX
    assert "body{overflow-x:hidden" not in INDEX


def test_copy_controls_cover_receipt_and_mcp_endpoints():
    for target in ("outcomeReceipt", "productMcpUrl", "mcpUrl", "mcpExample"):
        assert f'data-copy-target="{target}"' in INDEX
    assert "async function copyTarget(button)" in APP
    assert "navigator.clipboard.writeText(value)" in APP
    assert 'src="/app.js?v=20260919-ui4"' in INDEX


def test_judge_facing_navigation_and_score_labels_are_explicit():
    assert "https://github.com/ShahadatTest/apivouch" in INDEX
    assert 'href="#quick-connect">Connect MCP</a>' in INDEX
    assert '<div class="metric-kicker">Before</div>' in INDEX
    assert '<div class="metric-kicker">After</div>' in INDEX
    assert "points`" in APP


def test_findings_expose_counts_and_severity_filters():
    assert 'id="findingSummary"' in INDEX
    assert 'data-finding-filter="${severity}"' in APP
    assert 'findingFilter = button.dataset.findingFilter' in APP
