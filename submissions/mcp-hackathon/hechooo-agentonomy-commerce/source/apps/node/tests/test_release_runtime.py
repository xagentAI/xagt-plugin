from __future__ import annotations

import tempfile
import unittest
from contextlib import redirect_stdout
from dataclasses import replace
import io
import json
import os
from pathlib import Path
from unittest.mock import patch

from clink_node.config import (
    ExecutionGateSettings,
    NodeSettings,
    Profile,
    SecretBackend,
    StorageSettings,
    StorageBackend,
)
from clink_node.cli import main
from clink_node.paths import NodePaths
from clink_node.release_runtime import (
    ReleaseRuntimePolicy,
    UnsafeReleaseConfiguration,
    release_node_paths,
    run_release_self_check,
    runtime_root,
    validate_release_writable_paths,
)


class _FakeSelfCheckDependencies:
    def __init__(self) -> None:
        self.imports: list[str] = []
        self.paths: list[Path] = []

    def import_available(self, module_name: str) -> bool:
        self.imports.append(module_name)
        return True

    def path_is_file(self, path: Path) -> bool:
        self.paths.append(path)
        return True


class ReleaseRuntimeTests(unittest.TestCase):
    def _release_environment(self, root: Path) -> tuple[dict[str, str], Path]:
        version_root = root / "version"
        launcher_home = root / "launcher-home"
        version_root.mkdir()
        launcher_home.mkdir()
        return {
            "CLINK_RUNTIME_ROOT": str(version_root),
            "HOME": str(launcher_home),
        }, launcher_home / ".clink"

    def test_release_paths_are_launcher_owned_and_personal_only(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            env, state_root = self._release_environment(Path(temporary))
            paths = release_node_paths(env)
            self.assertEqual(paths.home, state_root.resolve(strict=False))
            settings = NodeSettings.load(env=env)

        self.assertTrue(settings.release_mode)
        self.assertEqual(settings.profile, Profile.PERSONAL)
        self.assertEqual(
            settings.paths.home,
            state_root.resolve(strict=False),
        )
        self.assertEqual(settings.storage.backend, StorageBackend.SQLITE)
        self.assertEqual(
            settings.storage.sqlite_path,
            (state_root / "data" / "clink.db").resolve(strict=False),
        )

    def test_release_rejects_live_gate_environment_and_toml_values(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            env, state_root = self._release_environment(root)
            state_paths = NodePaths.from_home(state_root)
            state_paths.ensure()
            config = state_paths.config
            config.write_text(
                "[execution]\nlive_funding = true\n",
                encoding="utf-8",
            )
            config.chmod(0o600)
            with self.assertRaises(UnsafeReleaseConfiguration):
                NodeSettings.load(env={**env, "CLINK_LIVE_FUNDING": "true"})
            with self.assertRaises(UnsafeReleaseConfiguration):
                NodeSettings.load(env=env)

    def test_policy_rejects_server_public_or_external_release_topology(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            paths = NodePaths.from_home(Path(temporary) / ".clink")
            baseline = NodeSettings.defaults(Profile.PERSONAL, paths=paths)
            for candidate in (
                replace(baseline, profile=Profile.SERVER),
                replace(baseline, host="0.0.0.0"),
                replace(baseline, mcp_host="::1"),
                replace(
                    baseline,
                    execution=replace(
                        baseline.execution,
                        live_funding=True,
                    ),
                ),
                replace(
                    baseline,
                    modules={
                        **baseline.modules,
                        "core": replace(
                            baseline.modules["core"],
                            endpoint="https://core.example",
                        ),
                    },
                ),
            ):
                with self.subTest(candidate=candidate):
                    with self.assertRaises(UnsafeReleaseConfiguration):
                        ReleaseRuntimePolicy.validate(candidate)

    def test_policy_accepts_only_literal_ipv4_loopback_hosts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            paths = NodePaths.from_home(Path(temporary) / ".clink")
            baseline = NodeSettings.defaults(Profile.PERSONAL, paths=paths)
            for host in ("127.0.0.1", "127.42.7.9"):
                with self.subTest(host=host):
                    ReleaseRuntimePolicy.validate(
                        replace(baseline, host=host, mcp_host=host)
                    )
            for host in ("localhost", "::1", "127.0.0.1.example"):
                with self.subTest(host=host):
                    with self.assertRaises(UnsafeReleaseConfiguration):
                        ReleaseRuntimePolicy.validate(
                            replace(baseline, host=host)
                        )

    def test_release_rejects_state_paths_outside_launcher_home(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            env, state_root = self._release_environment(root)
            paths = NodePaths.from_home(state_root)
            settings = NodeSettings.defaults(Profile.PERSONAL, paths=paths)
            settings = replace(
                settings,
                release_mode=True,
                storage=StorageSettings(
                    backend=StorageBackend.SQLITE,
                    sqlite_path=root / "outside.db",
                ),
            )
            with self.assertRaises(UnsafeReleaseConfiguration):
                validate_release_writable_paths(settings, env)

    def test_self_check_only_probes_declared_imports_and_layout(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            env, state_root = self._release_environment(root)
            settings = NodeSettings.load(env=env)
            dependencies = _FakeSelfCheckDependencies()
            report = run_release_self_check(
                settings,
                env=env,
                dependencies=dependencies,
            )

            self.assertEqual(report["status"], "ok")
            self.assertEqual(
                dependencies.imports,
                [
                    "clink_node.config",
                    "clink_node.runtime",
                    "clink_node.application",
                    "clink_node.cli",
                ],
            )
            self.assertFalse(state_root.exists())

    def test_runtime_root_requires_absolute_existing_launcher_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaises(ValueError):
                runtime_root({"CLINK_RUNTIME_ROOT": "relative"})
            with self.assertRaises(FileNotFoundError):
                runtime_root({"CLINK_RUNTIME_ROOT": str(root / "missing")})

    def test_cli_self_check_does_not_load_user_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "release"
            for module in ("core", "marketplace", "prediction-markets"):
                module_root = root / "apps" / module
                module_root.mkdir(parents=True)
                for script in (
                    "run_demo.sh",
                    "run_demo_stop.sh",
                    "run_demo_status.sh",
                ):
                    (module_root / script).write_text("", encoding="utf-8")
            launcher_home = Path(temporary) / "launcher-home"
            launcher_home.mkdir()
            environment = {
                "CLINK_RUNTIME_ROOT": str(root),
                "HOME": str(launcher_home),
            }
            output = io.StringIO()
            with patch.dict(os.environ, environment, clear=True):
                with patch(
                    "clink_node.cli.NodeSettings.load",
                    side_effect=AssertionError("state load"),
                ):
                    with redirect_stdout(output):
                        code = main(
                            ["doctor", "--release-self-check", "--json"]
                        )

            self.assertEqual(code, 0)
            self.assertEqual(json.loads(output.getvalue())["status"], "ok")
            self.assertFalse((launcher_home / ".clink").exists())

    def test_node_paths_do_not_follow_home_symlinks(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "target"
            target.mkdir()
            alias = root / "alias"
            alias.symlink_to(target, target_is_directory=True)
            with self.assertRaises(PermissionError):
                NodePaths.from_home(alias).ensure()

    def test_non_loopback_development_requires_https_vault(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            paths = NodePaths.from_home(Path(temporary) / ".clink")
            settings = NodeSettings.defaults(Profile.PERSONAL, paths=paths)
            settings = replace(
                settings,
                host="192.0.2.20",
                secrets=replace(
                    settings.secrets,
                    backend=SecretBackend.VAULT,
                    vault_address="http://vault.example",
                    vault_token="token",
                ),
            )
            self.assertTrue(
                any(
                    "HTTPS" in error or "non-loopback" in error
                    for error in settings.validation_errors()
                )
            )


if __name__ == "__main__":
    unittest.main()
