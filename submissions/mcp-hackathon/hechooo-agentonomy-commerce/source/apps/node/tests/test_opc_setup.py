from __future__ import annotations

import json
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest

from clink_node import opc_cli, opc_setup
from clink_node.opc_client import OpcClient, OpcClientStateStore
from clink_node.opc_setup import (
    DEFAULT_OPC_ORIGIN,
    ConfigConflictError,
    default_device_label,
    prepare_opc_state,
    resolve_codex_config_path,
    setup_opc,
    write_codex_config,
)


def test_default_label_is_bounded_and_control_free(monkeypatch: pytest.MonkeyPatch) -> None:
    assert default_device_label("work\nstation.example") == "OPC - work-station.example"
    assert len(default_device_label("a" * 200)) <= 80

    monkeypatch.setattr("socket.gethostname", lambda: "\x00\n")
    assert default_device_label() == "OPC device"


def test_default_origin_and_state_path_preserve_existing_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CLINK_HOME", str(tmp_path / "clink"))
    namespace = SimpleNamespace(state=None)
    assert opc_cli._state_path(namespace) == tmp_path / "clink/opc/client.json"
    assert DEFAULT_OPC_ORIGIN == "https://agentonomy.xyz"


def test_existing_state_keeps_origin_label_and_key_when_flags_are_omitted(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "clink/opc/client.json"
    first, created, _ = prepare_opc_state(
        state_path,
        server="https://legacy.example",
        label="legacy device",
    )
    first_identity = first.state.installation_id
    first.close()
    assert created is True

    second, created, _ = prepare_opc_state(state_path)
    try:
        assert created is False
        assert second.state.installation_id == first_identity
        assert second.state.origin == "https://legacy.example"
        assert second.state.label == "legacy device"
    finally:
        second.close()


def test_codex_config_appends_managed_entry_and_preserves_unrelated_bytes(
    tmp_path: Path,
) -> None:
    config = tmp_path / "config.toml"
    original = b"# keep this byte\n[ui]\ncolor = \"dark\"\n"
    config.write_bytes(original)
    executable = tmp_path / "prefix/bin/clink"
    executable.parent.mkdir(parents=True)
    executable.write_text("#!/bin/sh\n", encoding="utf-8")
    executable.chmod(0o755)
    state = tmp_path / "state/client.json"

    result = write_codex_config(config, executable=executable, state_path=state)

    assert result.changed is True
    updated = config.read_bytes()
    assert updated.startswith(original)
    assert "# BEGIN CLINK OPC MANAGED" in updated.decode()
    assert "https://agentonomy.xyz" not in updated.decode()
    assert json.loads(
        json.dumps({"command": str(executable.absolute()), "args": ["opc", "mcp", "--state", str(state.absolute())]})
    )
    backups = list(tmp_path.glob(".config.toml.clink-opc-backup-*"))
    assert len(backups) == 1
    assert stat.S_IMODE(backups[0].stat().st_mode) == 0o600
    assert backups[0].read_bytes() == original


def test_codex_config_updates_package_executable_only_for_same_state(
    tmp_path: Path,
) -> None:
    config = tmp_path / "config.toml"
    original = b"[ui]\ncolor = 'dark'\n"
    config.write_bytes(original)
    old_executable = tmp_path / "old/bin/clink"
    old_executable.parent.mkdir(parents=True)
    old_executable.write_text("old", encoding="utf-8")
    old_executable.chmod(0o755)
    new_executable = tmp_path / "new/bin/clink"
    new_executable.parent.mkdir(parents=True)
    new_executable.write_text("new", encoding="utf-8")
    new_executable.chmod(0o755)
    state = tmp_path / "state/client.json"

    write_codex_config(config, executable=old_executable, state_path=state)
    before_upgrade = config.read_bytes()
    result = write_codex_config(config, executable=new_executable, state_path=state)

    assert result.changed is True
    upgraded = config.read_bytes()
    assert upgraded.startswith(original)
    assert str(new_executable.absolute()).encode() in upgraded
    assert str(old_executable.absolute()).encode() not in upgraded
    assert result.backup is not None
    assert result.backup.read_bytes() == before_upgrade


def test_codex_config_identical_entry_is_noop_and_state_conflict_refuses_write(
    tmp_path: Path,
) -> None:
    config = tmp_path / "config.toml"
    executable = tmp_path / "clink"
    executable.write_text("runner", encoding="utf-8")
    executable.chmod(0o755)
    state = tmp_path / "state.json"
    write_codex_config(config, executable=executable, state_path=state)
    before = config.read_bytes()

    result = write_codex_config(config, executable=executable, state_path=state)
    assert result.changed is False
    assert config.read_bytes() == before
    assert len(list(tmp_path.glob(".config.toml.clink-opc-backup-*"))) == 0

    with pytest.raises(ConfigConflictError):
        write_codex_config(
            config,
            executable=executable,
            state_path=tmp_path / "other-state.json",
        )
    assert config.read_bytes() == before


def test_codex_config_semantically_identical_entry_is_also_a_noop(
    tmp_path: Path,
) -> None:
    config = tmp_path / "config.toml"
    executable = tmp_path / "clink"
    executable.write_text("runner", encoding="utf-8")
    executable.chmod(0o755)
    state = tmp_path / "state.json"
    config.write_text(
        "# BEGIN CLINK OPC MANAGED\n"
        "[mcp_servers.clink_node]\n"
        f"command = '{executable.absolute()}'\n"
        f"args = ['opc', 'mcp', '--state', '{state.absolute()}']\n"
        "# END CLINK OPC MANAGED\n",
        encoding="utf-8",
    )

    before = config.read_bytes()
    result = write_codex_config(config, executable=executable, state_path=state)

    assert result.changed is False
    assert config.read_bytes() == before
    assert not list(tmp_path.glob(".config.toml.clink-opc-backup-*"))


def test_codex_config_rejects_entry_extended_outside_managed_block(
    tmp_path: Path,
) -> None:
    config = tmp_path / "config.toml"
    executable = tmp_path / "clink"
    executable.write_text("runner", encoding="utf-8")
    executable.chmod(0o755)
    state = tmp_path / "state.json"
    config.write_text(
        "# BEGIN CLINK OPC MANAGED\n"
        "[mcp_servers.clink_node]\n"
        f"command = '{executable.absolute()}'\n"
        f"args = ['opc', 'mcp', '--state', '{state.absolute()}']\n"
        "# END CLINK OPC MANAGED\n"
        "unrelated = true\n",
        encoding="utf-8",
    )

    before = config.read_bytes()
    with pytest.raises(ConfigConflictError, match="rendered"):
        write_codex_config(config, executable=executable, state_path=state)
    assert config.read_bytes() == before


def test_codex_config_rejects_invalid_toml_symlink_and_unmanaged_entry(
    tmp_path: Path,
) -> None:
    executable = tmp_path / "clink"
    executable.write_text("runner", encoding="utf-8")
    executable.chmod(0o755)
    state = tmp_path / "state.json"

    invalid = tmp_path / "invalid.toml"
    invalid.write_text("[broken", encoding="utf-8")
    with pytest.raises(ValueError, match="TOML"):
        write_codex_config(invalid, executable=executable, state_path=state)

    unmanaged = tmp_path / "unmanaged.toml"
    unmanaged.write_text(
        '[mcp_servers.clink_node]\ncommand = "other"\nargs = []\n',
        encoding="utf-8",
    )
    with pytest.raises(ConfigConflictError):
        write_codex_config(unmanaged, executable=executable, state_path=state)

    target = tmp_path / "target.toml"
    target.write_text("[ui]\nvalue = true\n", encoding="utf-8")
    symlink = tmp_path / "link.toml"
    symlink.symlink_to(target)
    with pytest.raises(ValueError, match="symlink"):
        write_codex_config(symlink, executable=executable, state_path=state)

    real_parent = tmp_path / "real-parent"
    real_parent.mkdir()
    symlink_parent = tmp_path / "symlink-parent"
    symlink_parent.symlink_to(real_parent, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        write_codex_config(
            symlink_parent / "config.toml",
            executable=executable,
            state_path=state,
        )

    wrong_parent_shape = tmp_path / "wrong-parent.toml"
    wrong_parent_shape.write_text("mcp_servers = []\n", encoding="utf-8")
    with pytest.raises(ConfigConflictError):
        write_codex_config(wrong_parent_shape, executable=executable, state_path=state)


def test_codex_config_refuses_a_change_after_planning(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    config.write_text("[ui]\nvalue = true\n", encoding="utf-8")
    executable = tmp_path / "clink"
    executable.write_text("runner", encoding="utf-8")
    executable.chmod(0o755)
    plan = opc_setup._plan_codex_config(
        config,
        executable=executable,
        state_path=tmp_path / "state.json",
    )
    config.write_text("[ui]\nvalue = false\n", encoding="utf-8")
    with pytest.raises(ConfigConflictError, match="changed"):
        opc_setup._apply_plan(plan)


def test_codex_config_refuses_a_change_after_noop_planning(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    executable = tmp_path / "clink"
    executable.write_text("runner", encoding="utf-8")
    executable.chmod(0o755)
    state = tmp_path / "state.json"
    write_codex_config(config, executable=executable, state_path=state)
    plan = opc_setup._plan_codex_config(
        config,
        executable=executable,
        state_path=state,
    )
    assert plan.changed is False
    config.write_bytes(config.read_bytes() + b"# changed after planning\n")

    with pytest.raises(ConfigConflictError, match="changed"):
        opc_setup._apply_plan(plan)


def test_codex_config_respects_explicit_codex_home_without_changing_state_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    codex_home = tmp_path / "codex"
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    assert resolve_codex_config_path() == codex_home / "config.toml"
    monkeypatch.delenv("CODEX_HOME")
    assert resolve_codex_config_path() == Path.home() / ".codex/config.toml"


def test_opc_parser_defaults_are_headless_compatible() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    opc_cli.configure_opc_parser(commands)

    connect = parser.parse_args(["opc", "connect", "--json"])
    assert connect.server is None
    assert connect.label is None
    assert connect.json is True
    assert connect.no_open is False
    assert connect.wait_seconds == 600

    mcp = parser.parse_args(["opc", "mcp"])
    assert mcp.state is None

    status = parser.parse_args(["opc", "status"])
    assert status.state is None


def test_human_connect_headless_prints_expiring_link_without_waiting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    pairing = {
        "installation_id": "opc_" + "a" * 40,
        "pairing_id": "pair-1",
        "verification_uri": "https://agentonomy.xyz/account/opc/pair-1",
        "expires_at": 1_800_000_600,
        "status": "pending",
    }

    class FakeClient:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            self.connect_calls = 0

        def __enter__(self) -> "FakeClient":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def status(self) -> dict[str, object]:
            return {"installation_id": pairing["installation_id"], "status": "unpaired"}

        def connect(self) -> dict[str, object]:
            self.connect_calls += 1
            return pairing

    monkeypatch.setattr(opc_cli, "OpcClient", FakeClient)
    monkeypatch.setattr(opc_cli, "_state_path", lambda _namespace: tmp_path / "client.json")
    monkeypatch.setattr(opc_cli.time, "sleep", lambda _seconds: pytest.fail("waited"))
    namespace = SimpleNamespace(
        state=None,
        server=None,
        label=None,
        allow_loopback_http=False,
        no_open=True,
        json=False,
        wait_seconds=0,
    )

    assert opc_cli._connect(namespace) == 0
    output = capsys.readouterr().out
    assert pairing["verification_uri"] in output
    assert "wallet" in output.lower()


def test_json_connect_is_one_shot_without_browser_or_wait(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    pairing = {
        "installation_id": "opc_" + "c" * 40,
        "pairing_id": "pair-json",
        "verification_uri": "https://agentonomy.xyz/account/pair-json",
        "expires_at": 1_800_000_600,
        "status": "pending",
    }

    class FakeClient:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        def __enter__(self) -> "FakeClient":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def status(self) -> dict[str, object]:
            return {"installation_id": pairing["installation_id"], "status": "unpaired"}

        def connect(self) -> dict[str, object]:
            return pairing

    monkeypatch.setattr(opc_cli, "OpcClient", FakeClient)
    monkeypatch.setattr(opc_cli, "_state_path", lambda _namespace: tmp_path / "client.json")
    monkeypatch.setattr(
        opc_cli,
        "open_wallet_browser",
        lambda _uri: pytest.fail("JSON connect must not open a browser"),
    )
    monkeypatch.setattr(
        opc_cli,
        "_wait_for_consent",
        lambda **_kwargs: pytest.fail("JSON connect must not wait"),
    )
    namespace = SimpleNamespace(
        state=None,
        server=None,
        label=None,
        allow_loopback_http=False,
        no_open=False,
        json=True,
        wait_seconds=600,
    )

    assert opc_cli._connect(namespace) == 0
    assert json.loads(capsys.readouterr().out) == pairing


@pytest.mark.parametrize("terminal_status", ["active", "revoked"])
def test_wait_for_consent_returns_authoritative_terminal_status_with_bounded_polls(
    monkeypatch: pytest.MonkeyPatch, terminal_status: str
) -> None:
    class FakeTime:
        monotonic_now = 0.0
        wall_now = 1_000
        sleeps: list[float] = []

        @classmethod
        def monotonic(cls) -> float:
            return cls.monotonic_now

        @classmethod
        def time(cls) -> int:
            return cls.wall_now

        @classmethod
        def sleep(cls, seconds: float) -> None:
            assert 0 < seconds <= 5
            cls.sleeps.append(seconds)
            cls.monotonic_now += seconds
            cls.wall_now += int(seconds)

    statuses = iter([
        {"status": "pending"},
        {"status": "pending"},
        {"status": terminal_status},
    ])

    class FakeClient:
        def status(self) -> dict[str, str]:
            return next(statuses)

    monkeypatch.setattr(opc_cli.time, "monotonic", FakeTime.monotonic)
    monkeypatch.setattr(opc_cli.time, "time", FakeTime.time)
    monkeypatch.setattr(opc_cli.time, "sleep", FakeTime.sleep)

    result = opc_cli._wait_for_consent(
        FakeClient(),
        expires_at=2_000,
        wait_seconds=12,
    )

    assert result == {"status": terminal_status}
    assert FakeTime.sleeps == [5, 5]


def test_wait_for_consent_stops_at_pairing_expiry_without_long_sleep(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeTime:
        monotonic_now = 0.0
        wall_now = 1_000
        sleeps: list[float] = []

        @classmethod
        def monotonic(cls) -> float:
            return cls.monotonic_now

        @classmethod
        def time(cls) -> int:
            return cls.wall_now

        @classmethod
        def sleep(cls, seconds: float) -> None:
            assert 0 < seconds <= 5
            cls.sleeps.append(seconds)
            cls.monotonic_now += seconds
            cls.wall_now += int(seconds)

    class FakeClient:
        def status(self) -> dict[str, str]:
            return {"status": "pending"}

    monkeypatch.setattr(opc_cli.time, "monotonic", FakeTime.monotonic)
    monkeypatch.setattr(opc_cli.time, "time", FakeTime.time)
    monkeypatch.setattr(opc_cli.time, "sleep", FakeTime.sleep)

    assert (
        opc_cli._wait_for_consent(
            FakeClient(),
            expires_at=1_003,
            wait_seconds=600,
        )
        is None
    )
    assert FakeTime.sleeps == [3]


def test_mcp_initializes_fresh_state_with_defaults_without_pairing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict[str, object]] = []

    class FakeClient:
        def __init__(self, _store: object, **kwargs: object) -> None:
            calls.append(kwargs)

        def __enter__(self) -> "FakeClient":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        async def serve_stdio(self) -> None:
            return None

    monkeypatch.setattr(opc_cli, "OpcClient", FakeClient)
    monkeypatch.setattr(opc_cli.anyio, "run", lambda function: None)
    monkeypatch.setenv("CLINK_HOME", str(tmp_path / "clink"))
    namespace = SimpleNamespace(state=None)

    assert opc_cli._mcp(namespace) == 0
    assert calls == [{
        "allow_loopback_http": False,
        "origin": DEFAULT_OPC_ORIGIN,
        "label": default_device_label(),
    }]


def test_connect_skips_pairing_when_authoritative_status_is_active(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    class FakeClient:
        connect_calls = 0

        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        def __enter__(self) -> "FakeClient":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def status(self) -> dict[str, object]:
            return {"installation_id": "opc_" + "b" * 40, "status": "active"}

        def connect(self) -> dict[str, object]:
            type(self).connect_calls += 1
            raise AssertionError("active devices must not create another pairing")

    monkeypatch.setattr(opc_cli, "OpcClient", FakeClient)
    monkeypatch.setattr(opc_cli, "_state_path", lambda _namespace: tmp_path / "client.json")
    namespace = SimpleNamespace(
        state=None,
        server=None,
        label=None,
        allow_loopback_http=False,
        no_open=False,
        json=True,
        wait_seconds=600,
    )

    assert opc_cli._connect(namespace) == 0
    assert FakeClient.connect_calls == 0
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "active"


def test_generic_setup_prepares_state_and_emits_only_secret_free_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    executable = tmp_path / "prefix/bin/clink"
    executable.parent.mkdir(parents=True)
    executable.write_text("runner", encoding="utf-8")
    executable.chmod(0o755)
    state = tmp_path / "clink/opc/client.json"

    assert setup_opc(
        agent="generic",
        state_path=state,
        executable=executable,
    ) == 0

    output = capsys.readouterr()
    document = json.loads(output.out)
    assert document["command"] == str(executable.absolute())
    assert document["args"] == ["opc", "mcp", "--state", str(state.absolute())]
    assert "access_token" not in output.out
    assert "https://" not in output.out
    assert state.is_file()


def test_setup_preserves_state_created_by_concurrent_writer_on_config_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = tmp_path / "config.toml"
    config.write_text("[ui]\ncolor = 'dark'\n", encoding="utf-8")
    executable = tmp_path / "prefix/bin/clink"
    executable.parent.mkdir(parents=True)
    executable.write_text("runner", encoding="utf-8")
    executable.chmod(0o755)
    state = tmp_path / "clink/opc/client.json"
    concurrent_installation: list[str] = []
    original_state_exists = opc_setup._state_exists

    def race_state_exists(path: Path) -> bool:
        exists = original_state_exists(path)
        if not exists:
            writer = OpcClient(
                OpcClientStateStore(path),
                origin=DEFAULT_OPC_ORIGIN,
                label="concurrent device",
            )
            concurrent_installation.append(writer.state.installation_id)
            writer.close()
        return exists

    def fail_config(_plan: object):
        raise ConfigConflictError("injected config race")

    monkeypatch.setattr(opc_setup, "_state_exists", race_state_exists)
    monkeypatch.setattr(opc_setup, "_apply_plan", fail_config)

    with pytest.raises(ConfigConflictError, match="state was preserved"):
        setup_opc(
            agent="codex",
            state_path=state,
            config_path=config,
            executable=executable,
        )

    assert concurrent_installation
    loaded = OpcClientStateStore(state).load()
    assert loaded.installation_id == concurrent_installation[0]


def test_interactive_generic_setup_keeps_selection_prompt_off_stdout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fake_choose_agent(*, output):
        output("prompt")
        return "generic"

    def fake_setup_opc(**kwargs):
        del kwargs
        print('{"command":"/owned/clink"}')
        print("guide", file=opc_cli.sys.stderr)
        return 0

    monkeypatch.setattr(opc_cli, "choose_agent", fake_choose_agent)
    monkeypatch.setattr(opc_cli, "setup_opc", fake_setup_opc)
    namespace = SimpleNamespace(
        agent=None,
        state=tmp_path / "state.json",
        config=None,
        server=None,
        label=None,
        allow_loopback_http=False,
    )

    assert opc_cli._setup(namespace) == 0
    captured = capsys.readouterr()
    assert captured.out == '{"command":"/owned/clink"}\n'
    assert captured.err == "prompt\nguide\n"
