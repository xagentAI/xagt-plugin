from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from scripts.bazaar_pilot_smoke import run_smoke
from shared.config import AppConfig


def test_bazaar_pilot_smoke_covers_trusted_purchase_flow() -> None:
    result = run_smoke()

    assert result["status"] == "ok"
    assert result["sync"]["status"] == "succeeded"
    assert result["candidate"]["status"] == "discovered"
    assert result["unverified_public_count"] == 0
    assert result["verified"]["status"] == "verified"
    assert result["public_search"]["count"] == 1
    assert result["purchase"]["state"] == "delivered"
    assert result["purchase"]["reason_code"] is None
    assert result["service_result"] == {"status": "ok", "risk": "low"}
    assert result["replay_service_result"] is None
    assert result["core_calls"] == {"reserve": 1, "settle": 1}
    assert result["merchant_deliveries"] == 1
    assert result["reputation"]["sample_size"] == 1
    assert result["persistence"]["plaintext_found"] is False
    assert result["references"]["action_id"]
    assert result["references"]["policy_decision_id"]
    assert result["references"]["receipt_id"]
    assert result["references"]["audit_event_ids"]


def test_local_runtime_uses_the_documented_redis_url(monkeypatch) -> None:
    monkeypatch.delenv("MARKETPLACE_REDIS_URL", raising=False)
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:6380/7")

    assert AppConfig.from_env().redis_url == "redis://127.0.0.1:6380/7"


def test_alembic_cli_can_load_revision_graph() -> None:
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "heads"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "20260904_0010 (head)" in result.stdout
