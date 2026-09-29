from pathlib import Path

import pytest

from app.certificates import verify_report
from app.contracts import ChallengeRequest
from app.demo import fixture
from app.lab import challenge
from tools.local_smoke import ROOT, offline_environment, tamper_report


def test_offline_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEXUS_API_KEY", "must-not-propagate")
    monkeypatch.setenv("OTHER_SECRET", "must-not-propagate")
    monkeypatch.setenv("ALPHALITMUS_ENABLE_NEXUS", "true")
    monkeypatch.setenv("ALPHALITMUS_ENABLE_NEXUS_BACKTEST", "true")
    monkeypatch.setenv("HTTPS_PROXY", "must-not-propagate")
    temporary = ROOT / ".smoke-test-temp"
    env = offline_environment(temporary)
    assert "must-not-propagate" not in env.values()
    assert env["ALPHALITMUS_ENABLE_NEXUS"] == "false"
    assert env["ALPHALITMUS_ENABLE_NEXUS_BACKTEST"] == "false"
    assert env["ALPHALITMUS_ENV"] == "test"
    assert all(Path(env[key]).is_relative_to(ROOT) for key in ("TEMP", "TMP", "TMPDIR", "HOME"))


def test_reason_tamper_preserves_original() -> None:
    report = challenge(ChallengeRequest(research=fixture("mixed")))
    before = report.model_dump(mode="json")
    damaged = tamper_report(report)
    assert report.model_dump(mode="json") == before
    changed = damaged.model_dump(mode="json")
    changed["test_matrix"][0]["reason"] = before["test_matrix"][0]["reason"]
    assert changed == before
    assert verify_report(report).valid
    checked = verify_report(damaged)
    assert not checked.valid
    assert "CONTENT_HASH_MISMATCH" in checked.errors


def test_smoke_artifacts_remain_under_temporary_directory(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fresh-clone regression: smoke must not require or touch ROOT/reports/."""
    import tools.local_smoke as smoke

    written: list[Path] = []
    original_write = Path.write_text

    def recording(self: Path, *args: object, **kwargs: object) -> object:
        if self.name.startswith("alphalitmus-") and self.suffix == ".json":
            written.append(self)
        return original_write(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(Path, "write_text", recording)
    reports_dir = smoke.ROOT / "reports"
    before = sorted(p.name for p in reports_dir.iterdir()) if reports_dir.is_dir() else None
    smoke.run_smoke()
    assert written, "expected smoke to write verifier artifacts"
    for path in written:
        assert path.parent != reports_dir
        assert ".local-smoke-" in path.parent.name
        assert path.is_relative_to(smoke.ROOT)
    after = sorted(p.name for p in reports_dir.iterdir()) if reports_dir.is_dir() else None
    assert after == before
