from __future__ import annotations

from dataclasses import dataclass

import pytest

import production
from execution_models import ExecutionState


@dataclass
class Result:
    status: ExecutionState


class FakeReconciler:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.error: Exception | None = None

    def inspect_submission_with_evidence(
        self, execution_id: str
    ) -> tuple[Result, bool]:
        self.calls.append(("inspect", execution_id))
        if self.error is not None:
            raise self.error
        return Result(ExecutionState.SUBMISSION_UNKNOWN), False

    def rebroadcast_identical(self, execution_id: str) -> Result:
        self.calls.append(("rebroadcast", execution_id))
        if self.error is not None:
            raise self.error
        return Result(ExecutionState.SUBMITTED)


class FakeResource:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


def install_builder(
    monkeypatch: pytest.MonkeyPatch,
    reconciler: FakeReconciler,
    resource: FakeResource,
) -> list[None]:
    builds: list[None] = []

    def build():
        builds.append(None)
        return reconciler, [resource]

    monkeypatch.setattr(production, "build_production_reconciler", build)
    return builds


def test_reconcile_cli_inspects_without_broadcast(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    reconciler = FakeReconciler()
    resource = FakeResource()
    install_builder(monkeypatch, reconciler, resource)

    result = production.main(
        ["reconcile-execution", "--execution-id", "exec_123", "--inspect"]
    )

    captured = capsys.readouterr()
    assert result == 0
    assert captured.out == (
        "execution reconciliation status: submission_unknown; "
        "exact_transaction_found=false\n"
    )
    assert captured.err == ""
    assert reconciler.calls == [("inspect", "exec_123")]
    assert resource.closed is True


def test_reconcile_cli_explicitly_rebroadcasts_only_the_requested_execution(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    reconciler = FakeReconciler()
    resource = FakeResource()
    install_builder(monkeypatch, reconciler, resource)

    result = production.main(
        ["reconcile-execution", "--execution-id", "exec_123", "--rebroadcast"]
    )

    captured = capsys.readouterr()
    assert result == 0
    assert captured.out == "execution reconciliation status: submitted\n"
    assert captured.err == ""
    assert reconciler.calls == [("rebroadcast", "exec_123")]
    assert resource.closed is True


def test_reconcile_cli_rejects_invalid_execution_id_before_building_runtime(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    reconciler = FakeReconciler()
    resource = FakeResource()
    builds = install_builder(monkeypatch, reconciler, resource)

    result = production.main(
        ["reconcile-execution", "--execution-id", "bad id", "--inspect"]
    )

    captured = capsys.readouterr()
    assert result == 2
    assert captured.out == ""
    assert captured.err == "execution-id is invalid\n"
    assert builds == []
    assert resource.closed is False


def test_reconcile_cli_hides_dependency_errors_and_secrets(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    reconciler = FakeReconciler()
    reconciler.error = RuntimeError(
        "postgresql+psycopg://user:secret@db raw=0xdeadbeef"
    )
    resource = FakeResource()
    install_builder(monkeypatch, reconciler, resource)

    result = production.main(
        ["reconcile-execution", "--execution-id", "exec_123", "--inspect"]
    )

    captured = capsys.readouterr()
    assert result == 1
    assert captured.out == ""
    assert captured.err == "execution reconciliation failed\n"
    assert "secret" not in captured.err
    assert "deadbeef" not in captured.err
    assert resource.closed is True


def test_reconcile_cli_requires_exactly_one_action(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as raised:
        production.main(["reconcile-execution", "--execution-id", "exec_123"])

    assert raised.value.code == 2
    assert "one of the arguments --inspect --rebroadcast is required" in (
        capsys.readouterr().err
    )
