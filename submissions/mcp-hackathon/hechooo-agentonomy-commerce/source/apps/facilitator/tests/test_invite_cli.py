from __future__ import annotations

import pytest

import production


class FakeEngine:
    def __init__(self) -> None:
        self.disposed = False

    def dispose(self) -> None:
        self.disposed = True


class FakeRepository:
    instances: list["FakeRepository"] = []

    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        self.engine = FakeEngine()
        self.__class__.instances.append(self)


class FakeEnrollmentService:
    instances: list["FakeEnrollmentService"] = []
    token = "invite-secret"
    error: Exception | None = None

    def __init__(self, *, repository: object, enrollment_ttl_seconds: int, clock: object) -> None:
        self.repository = repository
        self.enrollment_ttl_seconds = enrollment_ttl_seconds
        self.clock = clock
        self.__class__.instances.append(self)

    def issue_enrollment_token(self, tenant_id: str) -> str:
        self.tenant_id = tenant_id
        if self.__class__.error is not None:
            raise self.__class__.error
        return self.__class__.token


@pytest.fixture(autouse=True)
def reset_fakes() -> None:
    FakeRepository.instances.clear()
    FakeEnrollmentService.instances.clear()
    FakeEnrollmentService.error = None


def install_fakes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("repository.PostgresRepository", FakeRepository)
    monkeypatch.setattr("enrollment.EnrollmentService", FakeEnrollmentService)


def test_issue_invite_uses_hosted_postgres_and_prints_plaintext_once(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    install_fakes(monkeypatch)
    monkeypatch.setenv("CLINK_HOSTED_POSTGRES_URL", "postgresql+psycopg://hosted/primary")
    monkeypatch.setenv("ALEMBIC_DATABASE_URL", "postgresql+psycopg://wrong/secondary")

    result = production.main(
        ["issue-invite", "--tenant-id", "tenant_1", "--ttl-seconds", "60"]
    )

    captured = capsys.readouterr()
    assert result == 0
    assert captured.out == "invite-secret\n"
    assert captured.err == ""
    assert len(FakeRepository.instances) == 1
    repository = FakeRepository.instances[0]
    assert repository.database_url == "postgresql+psycopg://hosted/primary"
    assert repository.engine.disposed is True
    assert len(FakeEnrollmentService.instances) == 1
    service = FakeEnrollmentService.instances[0]
    assert service.tenant_id == "tenant_1"
    assert service.enrollment_ttl_seconds == 60
    assert service.repository is repository


def test_issue_invite_falls_back_to_alembic_postgres_url(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    install_fakes(monkeypatch)
    monkeypatch.delenv("CLINK_HOSTED_POSTGRES_URL", raising=False)
    monkeypatch.setenv("ALEMBIC_DATABASE_URL", "postgresql+psycopg://hosted/migration")

    result = production.main(
        ["issue-invite", "--tenant-id", "tenant_1", "--ttl-seconds", "300"]
    )

    captured = capsys.readouterr()
    assert result == 0
    assert captured.out == "invite-secret\n"
    assert captured.err == ""
    assert FakeRepository.instances[0].database_url == (
        "postgresql+psycopg://hosted/migration"
    )


@pytest.mark.parametrize("ttl_seconds", [29, 901])
def test_issue_invite_rejects_ttl_outside_strict_range(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    ttl_seconds: int,
) -> None:
    install_fakes(monkeypatch)
    monkeypatch.setenv("CLINK_HOSTED_POSTGRES_URL", "postgresql+psycopg://hosted/primary")

    result = production.main(
        ["issue-invite", "--tenant-id", "tenant_1", "--ttl-seconds", str(ttl_seconds)]
    )

    captured = capsys.readouterr()
    assert result == 2
    assert captured.out == ""
    assert "30" in captured.err and "900" in captured.err
    assert FakeRepository.instances == []
    assert FakeEnrollmentService.instances == []


def test_issue_invite_rejects_invalid_tenant_before_connecting(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    install_fakes(monkeypatch)
    monkeypatch.setenv("CLINK_HOSTED_POSTGRES_URL", "postgresql+psycopg://hosted/primary")

    result = production.main(
        ["issue-invite", "--tenant-id", "tenant with spaces", "--ttl-seconds", "60"]
    )

    captured = capsys.readouterr()
    assert result == 2
    assert captured.out == ""
    assert "tenant-id is invalid" in captured.err
    assert FakeRepository.instances == []


def test_issue_invite_hides_token_when_database_operation_fails(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    install_fakes(monkeypatch)
    FakeEnrollmentService.error = RuntimeError("provider leaked invite-secret")
    monkeypatch.setenv("CLINK_HOSTED_POSTGRES_URL", "postgresql+psycopg://user:secret@hosted/db")

    result = production.main(
        ["issue-invite", "--tenant-id", "tenant_1", "--ttl-seconds", "60"]
    )

    captured = capsys.readouterr()
    assert result == 1
    assert captured.out == ""
    assert captured.err == "invite could not be issued\n"
    assert "invite-secret" not in captured.err
    assert "user:secret" not in captured.err
    assert FakeRepository.instances[0].engine.disposed is True


def test_issue_invite_does_not_accept_plaintext_token_argument(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as raised:
        production.main(
            [
                "issue-invite",
                "--tenant-id",
                "tenant_1",
                "--ttl-seconds",
                "60",
                "--token",
                "invite-secret",
            ]
        )

    assert raised.value.code == 2
    assert "invite-secret" not in capsys.readouterr().err
