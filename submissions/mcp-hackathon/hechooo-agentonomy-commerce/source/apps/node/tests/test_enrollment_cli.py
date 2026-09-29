from __future__ import annotations

import io
import json
import os
import subprocess
import sys
from contextlib import redirect_stderr
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from clink_node.cli import _open_enrollment_manager, _parser, main
from clink_node.config import NodeSettings, Profile
from clink_node.instance_lock import InstanceLockError
from clink_node.paths import NodePaths


SECRET = "invite-secret-must-not-appear"


def test_existing_cli_help_imports_without_core_pythonpath(tmp_path: Path) -> None:
    environment = dict(os.environ)
    environment.pop("PYTHONPATH", None)

    result = subprocess.run(
        [sys.executable, "-m", "clink_node", "--help"],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    assert "Run the local-first Clink Node" in result.stdout


def _settings(tmp_path: Path, *, release_mode: bool = True) -> NodeSettings:
    paths = NodePaths.from_home(tmp_path / ".clink")
    paths.ensure()
    return replace(
        NodeSettings.defaults(Profile.PERSONAL, paths=paths),
        release_mode=release_mode,
    )


def test_parser_rejects_token_and_endpoint_without_echoing_secret() -> None:
    parser = _parser()
    for option in ("--token", "--endpoint"):
        stderr = io.StringIO()
        with redirect_stderr(stderr), pytest.raises(SystemExit):
            parser.parse_args(
                [
                    "enrollment",
                    "enroll",
                    "--wallet-binding-id",
                    "wallet_1",
                    option,
                    SECRET,
                ]
            )
        assert SECRET not in stderr.getvalue()


def test_enrollment_rejects_non_release_before_prompt_or_network(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path, release_mode=False)
    getpass = Mock(return_value="i" * 43)
    open_manager = Mock()
    with patch("clink_node.cli._load_valid_settings", return_value=settings), patch(
        "clink_node.cli.getpass.getpass", getpass
    ), patch(
        "clink_node.cli._open_enrollment_manager",
        open_manager,
        create=True,
    ):
        code = main(
            [
                "enrollment",
                "enroll",
                "--wallet-binding-id",
                "wallet_1",
            ]
        )
    assert code == 1
    getpass.assert_not_called()
    open_manager.assert_not_called()


def test_enrollment_rejects_running_node_before_prompt_or_network(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    getpass = Mock(return_value="i" * 43)
    open_manager = Mock()

    class BusyLock:
        def __enter__(self) -> object:
            raise InstanceLockError("busy")

        def __exit__(self, *_args: object) -> None:
            return None

    with patch("clink_node.cli._load_valid_settings", return_value=settings), patch(
        "clink_node.cli.InstanceLock", return_value=BusyLock()
    ), patch("clink_node.cli.getpass.getpass", getpass), patch(
        "clink_node.cli._open_enrollment_manager",
        open_manager,
        create=True,
    ):
        code = main(
            [
                "enrollment",
                "enroll",
                "--wallet-binding-id",
                "wallet_1",
            ]
        )
    assert code == 1
    getpass.assert_not_called()
    open_manager.assert_not_called()


class FakeTransport:
    def __init__(self) -> None:
        self.close = Mock()


class FakeManager:
    def __init__(self, bundle: object | None) -> None:
        self.bundle = bundle
        self.enroll = Mock(return_value=bundle)
        self.rotate = Mock(return_value=bundle)
        self.resume_rotation = Mock(return_value=bundle)
        self.revoke = Mock()
        self.resume_revocation = Mock()

    def current(self) -> object | None:
        return self.bundle


def _bundle(state: str = "active") -> SimpleNamespace:
    return SimpleNamespace(
        state=state,
        tenant_id="tenant_1",
        node_id="node_1",
        wallet_binding_id="wallet_1",
        credential_epoch=2,
        private_key_pkcs8_b64="private-key-secret",
        access_token="access-token-secret",
        trust_fingerprint="trust-secret",
        invite_digest="invite-digest-secret",
        rotation_id="rotation-secret",
        pending_private_key_pkcs8_b64="pending-key-secret",
        pending_access_token="pending-token-secret",
        revocation_id="revocation-secret",
    )


def test_enroll_uses_getpass_and_dispatches_pending_enrollment_once(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    manager = FakeManager(_bundle("enrollment_pending"))
    transport = FakeTransport()
    with patch("clink_node.cli._load_valid_settings", return_value=settings), patch(
        "clink_node.cli._open_enrollment_manager",
        return_value=(manager, transport),
        create=True,
    ), patch("clink_node.cli.getpass.getpass", return_value="i" * 43) as getpass:
        code = main(
            [
                "enrollment",
                "enroll",
                "--wallet-binding-id",
                "wallet_1",
            ]
        )
    assert code == 0
    getpass.assert_called_once()
    manager.enroll.assert_called_once_with(
        invite_code="i" * 43,
        wallet_binding_id="wallet_1",
    )
    transport.close.assert_called_once()


def test_rotate_and_revoke_resume_the_existing_pending_operation(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    for command, state, method in (
        ("rotate", "rotation_pending", "resume_rotation"),
        ("revoke", "revocation_pending", "resume_revocation"),
    ):
        manager = FakeManager(_bundle(state))
        transport = FakeTransport()
        with patch("clink_node.cli._load_valid_settings", return_value=settings), patch(
            "clink_node.cli._open_enrollment_manager",
            return_value=(manager, transport),
            create=True,
        ):
            code = main(["enrollment", command])
        assert code == 0
        getattr(manager, method).assert_called_once_with()
        transport.close.assert_called_once()


def test_rotate_active_starts_one_rotation_and_revoke_active_starts_one_revoke(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    for command, state, method in (
        ("rotate", "active", "rotate"),
        ("revoke", "active", "revoke"),
    ):
        manager = FakeManager(_bundle(state))
        transport = FakeTransport()
        with patch("clink_node.cli._load_valid_settings", return_value=settings), patch(
            "clink_node.cli._open_enrollment_manager",
            return_value=(manager, transport),
            create=True,
        ):
            code = main(["enrollment", command])
        assert code == 0
        getattr(manager, method).assert_called_once_with()
        transport.close.assert_called_once()


def test_status_json_contains_only_safe_fields_and_no_secret_values(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    settings = _settings(tmp_path)
    manager = FakeManager(_bundle("active"))
    transport = FakeTransport()
    with patch("clink_node.cli._load_valid_settings", return_value=settings), patch(
        "clink_node.cli._open_enrollment_manager",
        return_value=(manager, transport),
        create=True,
    ):
        assert main(["enrollment", "status", "--json"]) == 0
    output = capsys.readouterr().out
    payload = json.loads(output)
    assert set(payload) == {
        "state",
        "tenant_id",
        "node_id",
        "wallet_binding_id",
        "credential_epoch",
        "pending_action",
    }
    assert payload["state"] == "active"
    assert payload["pending_action"] is None
    for value in (
        "private-key-secret",
        "access-token-secret",
        "trust-secret",
        "invite-digest-secret",
        "rotation-secret",
        "pending-key-secret",
        "pending-token-secret",
        "revocation-secret",
    ):
        assert value not in output
    transport.close.assert_called_once()


def test_status_does_not_take_node_lock_while_node_is_running(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    manager = FakeManager(_bundle("active"))
    transport = FakeTransport()
    with patch("clink_node.cli._load_valid_settings", return_value=settings), patch(
        "clink_node.cli._open_enrollment_manager",
        return_value=(manager, transport),
        create=True,
    ), patch(
        "clink_node.cli.InstanceLock",
        side_effect=AssertionError("status must not take the Node lock"),
    ):
        assert main(["enrollment", "status", "--json"]) == 0
    transport.close.assert_called_once()


def test_export_core_wallet_bundle_writes_once_and_prints_only_safe_metadata(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    settings = _settings(tmp_path)
    bundle = _bundle("active")
    manager = FakeManager(bundle)
    transport = FakeTransport()
    output = (tmp_path / "private" / "core-wallet.json").resolve()
    output.parent.mkdir(mode=0o700)
    safe_result = {
        "status": "written",
        "path": str(output),
        "request_id": "provision_1",
        "user_id": "user_1",
        "wallet_identity_id": "wallet_identity_1",
        "tenant_id": "tenant_1",
        "node_id": "node_1",
        "wallet_binding_id": "wallet_1",
    }
    with patch("clink_node.cli._load_valid_settings", return_value=settings), patch(
        "clink_node.cli._open_enrollment_manager",
        return_value=(manager, transport),
        create=True,
    ), patch(
        "clink_node.cli.write_core_provisioning_bundle",
        return_value=safe_result,
        create=True,
    ) as writer:
        code = main(
            [
                "enrollment",
                "export-core-wallet-bundle",
                "--user-id",
                "user_1",
                "--wallet-identity-id",
                "wallet_identity_1",
                "--request-id",
                "provision_1",
                "--output",
                str(output),
            ]
        )

    assert code == 0
    writer.assert_called_once_with(
        bundle,
        user_id="user_1",
        wallet_identity_id="wallet_identity_1",
        request_id="provision_1",
        output_path=output,
    )
    rendered = capsys.readouterr().out
    assert json.loads(rendered) == safe_result
    assert "private-key-secret" not in rendered
    assert "access-token-secret" not in rendered
    transport.close.assert_called_once()


def test_manager_uses_release_trust_loader_and_application_secret_store(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    trust = SimpleNamespace(
        enrollment_endpoint="https://enroll.agentonomy.example/v1/enrollments"
    )
    runtime = Mock()
    runtime.return_value.load_trust.return_value = trust
    transport = FakeTransport()
    manager = object()

    with patch("clink_node.cli.HostedReleaseRuntime", runtime), patch(
        "clink_node.hosted_enrollment_transport.HttpxEnrollmentTransport",
        return_value=transport,
    ) as transport_factory, patch(
        "clink_node.cli.HostedEnrollmentManager", return_value=manager
    ) as manager_factory, patch(
        "clink_node.application._secret_store",
        return_value="store",
    ):
        opened_manager, opened_transport = _open_enrollment_manager(settings)

    assert opened_manager is manager
    assert opened_transport is transport
    runtime.assert_called_once_with(env=os.environ)
    runtime.return_value.load_trust.assert_called_once_with()
    transport_factory.assert_called_once_with(trust.enrollment_endpoint)
    manager_factory.assert_called_once()
    transport.close.assert_not_called()
