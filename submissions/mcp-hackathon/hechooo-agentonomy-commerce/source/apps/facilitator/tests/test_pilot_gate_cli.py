from __future__ import annotations

import pytest

import production


class FakeEngine:
    def __init__(self) -> None:
        self.disposed = False

    def dispose(self) -> None:
        self.disposed = True


class FakeExecutionRepository:
    instances: list["FakeExecutionRepository"] = []
    error: Exception | None = None

    def __init__(self, database_url: str, *, create_schema: bool) -> None:
        self.database_url = database_url
        self.create_schema = create_schema
        self.engine = FakeEngine()
        self.pause_calls: list[dict[str, object]] = []
        self.__class__.instances.append(self)

    def set_pilot_pause(self, **kwargs: object) -> None:
        if self.__class__.error is not None:
            raise self.__class__.error
        self.pause_calls.append(kwargs)


@pytest.fixture(autouse=True)
def reset_fakes() -> None:
    FakeExecutionRepository.instances.clear()
    FakeExecutionRepository.error = None


def install_fake(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "execution_repository.ExecutionRepository", FakeExecutionRepository
    )


def test_pilot_gate_pause_uses_hosted_postgres_and_fixed_output(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    install_fake(monkeypatch)
    monkeypatch.setenv("CLINK_HOSTED_POSTGRES_URL", "postgresql+psycopg://hosted/primary")
    monkeypatch.setenv("ALEMBIC_DATABASE_URL", "postgresql+psycopg://wrong/secondary")

    result = production.main(
        [
            "pilot-gate",
            "--scope",
            "platform",
            "--pause",
            "--reason-code",
            "operator_pause",
        ]
    )

    captured = capsys.readouterr()
    assert result == 0
    assert captured.out == "pilot gate paused\n"
    assert captured.err == ""
    repository = FakeExecutionRepository.instances[0]
    assert repository.database_url == "postgresql+psycopg://hosted/primary"
    assert repository.create_schema is False
    assert repository.pause_calls == [
        {
            "scope_type": "platform",
            "paused": True,
            "reason_code": "operator_pause",
            "tenant_id": "",
            "node_id": "",
        }
    ]
    assert repository.engine.disposed is True


def test_pilot_gate_resume_tenant_falls_back_to_alembic_url(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    install_fake(monkeypatch)
    monkeypatch.delenv("CLINK_HOSTED_POSTGRES_URL", raising=False)
    monkeypatch.setenv("ALEMBIC_DATABASE_URL", "postgresql+psycopg://hosted/migration")

    result = production.main(
        [
            "pilot-gate",
            "--scope",
            "tenant",
            "--tenant-id",
            "tenant_1",
            "--resume",
            "--reason-code",
            "operator_resume",
        ]
    )

    captured = capsys.readouterr()
    assert result == 0
    assert captured.out == "pilot gate resumed\n"
    assert captured.err == ""
    repository = FakeExecutionRepository.instances[0]
    assert repository.database_url == "postgresql+psycopg://hosted/migration"
    assert repository.pause_calls == [
        {
            "scope_type": "tenant",
            "paused": False,
            "reason_code": "operator_resume",
            "tenant_id": "tenant_1",
            "node_id": "",
        }
    ]


def test_pilot_gate_node_requires_tenant_and_node_before_connecting(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    install_fake(monkeypatch)
    monkeypatch.setenv("CLINK_HOSTED_POSTGRES_URL", "postgresql+psycopg://hosted/primary")

    result = production.main(
        [
            "pilot-gate",
            "--scope",
            "node",
            "--pause",
            "--reason-code",
            "operator_pause",
            "--node-id",
            "node_1",
        ]
    )

    captured = capsys.readouterr()
    assert result == 2
    assert captured.out == ""
    assert captured.err == "tenant-id and node-id are required for node scope\n"
    assert FakeExecutionRepository.instances == []


@pytest.mark.parametrize(
    ("scope", "extra_args", "message"),
    [
        (
            "platform",
            ["--tenant-id", "tenant_1"],
            "tenant-id and node-id are not allowed for platform scope\n",
        ),
        (
            "tenant",
            [],
            "tenant-id is required for tenant scope\n",
        ),
        (
            "tenant",
            ["--tenant-id", "tenant_1", "--node-id", "node_1"],
            "node-id is not allowed for tenant scope\n",
        ),
    ],
)
def test_pilot_gate_scope_shape_is_rejected_before_connecting(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    scope: str,
    extra_args: list[str],
    message: str,
) -> None:
    install_fake(monkeypatch)
    monkeypatch.setenv("CLINK_HOSTED_POSTGRES_URL", "postgresql+psycopg://hosted/primary")

    result = production.main(
        [
            "pilot-gate",
            "--scope",
            scope,
            "--pause",
            "--reason-code",
            "operator_pause",
            *extra_args,
        ]
    )

    captured = capsys.readouterr()
    assert result == 2
    assert captured.out == ""
    assert captured.err == message
    assert FakeExecutionRepository.instances == []


def test_pilot_gate_requires_exactly_one_action(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as raised:
        production.main(
            [
                "pilot-gate",
                "--scope",
                "platform",
                "--reason-code",
                "operator_pause",
            ]
        )

    assert raised.value.code == 2
    assert "one of the arguments --pause --resume is required" in capsys.readouterr().err


def test_pilot_gate_rejects_invalid_reason_code_before_connecting(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    install_fake(monkeypatch)
    monkeypatch.setenv("CLINK_HOSTED_POSTGRES_URL", "postgresql+psycopg://user:secret@hosted/db")

    result = production.main(
        [
            "pilot-gate",
            "--scope",
            "platform",
            "--pause",
            "--reason-code",
            "bad-reason",
        ]
    )

    captured = capsys.readouterr()
    assert result == 2
    assert captured.out == ""
    assert captured.err == "reason-code is invalid\n"
    assert "user:secret" not in captured.err
    assert FakeExecutionRepository.instances == []


def test_pilot_gate_requires_postgresql_url_before_connecting(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    install_fake(monkeypatch)
    monkeypatch.setenv("CLINK_HOSTED_POSTGRES_URL", "sqlite:///pilot.db")
    monkeypatch.delenv("ALEMBIC_DATABASE_URL", raising=False)

    result = production.main(
        [
            "pilot-gate",
            "--scope",
            "platform",
            "--pause",
            "--reason-code",
            "operator_pause",
        ]
    )

    captured = capsys.readouterr()
    assert result == 2
    assert captured.out == ""
    assert captured.err == "PostgreSQL URL is required\n"
    assert FakeExecutionRepository.instances == []


def test_pilot_gate_hides_database_error_and_url(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    install_fake(monkeypatch)
    FakeExecutionRepository.error = RuntimeError("postgresql+psycopg://user:secret@db leaked")
    monkeypatch.setenv("CLINK_HOSTED_POSTGRES_URL", "postgresql+psycopg://user:secret@hosted/db")

    result = production.main(
        [
            "pilot-gate",
            "--scope",
            "platform",
            "--pause",
            "--reason-code",
            "operator_pause",
        ]
    )

    captured = capsys.readouterr()
    assert result == 1
    assert captured.out == ""
    assert captured.err == "pilot gate update failed\n"
    assert "user:secret" not in captured.err
    assert FakeExecutionRepository.instances[0].engine.disposed is True


def test_pilot_gate_rejects_both_actions_without_connecting(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as raised:
        production.main(
            [
                "pilot-gate",
                "--scope",
                "platform",
                "--pause",
                "--resume",
                "--reason-code",
                "operator_pause",
            ]
        )

    assert raised.value.code == 2
    assert "not allowed with argument --pause" in capsys.readouterr().err
