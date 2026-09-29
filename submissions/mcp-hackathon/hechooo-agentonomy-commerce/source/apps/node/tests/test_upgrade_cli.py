from __future__ import annotations

import argparse
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from apps.node.clink_node.cli import _run_installer
from apps.node.clink_node.config import StorageBackend


class _Lifecycle:
    def __init__(self, events: list[object]) -> None:
        self.events = events

    def quiesce(self, *, reason: str) -> None:
        self.events.append(("quiesce", reason))

    def resume(self) -> None:
        self.events.append("resume")


class _SQLiteRepository:
    def __init__(self, events: list[object], *, fail: Exception | None = None) -> None:
        self.events = events
        self.fail = fail

    def checkpoint_and_validate(self) -> dict[str, object]:
        self.events.append("checkpoint")
        if self.fail is not None:
            raise self.fail
        return {"schema_version": 1}

    def create_upgrade_backup(self, destination: Path) -> Path:
        self.events.append(("backup", destination))
        return destination


def _namespace(root: Path, *, operation: str = "install") -> argparse.Namespace:
    values = {
        "installer": "clink-installer",
        "release_root": root / "releases",
        "public_key": None,
        "public_key_file": None,
    }
    if operation == "install":
        values.update({"bundle": root / "bundle.tar.gz", "version": "1.2.3"})
    return argparse.Namespace(**values)


class UpgradeCliTests(unittest.TestCase):
    def test_sqlite_backup_is_validated_after_quiesce_before_switch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            events: list[object] = []
            settings = SimpleNamespace(
                paths=SimpleNamespace(data=root / "data"),
                storage=SimpleNamespace(
                    backend=StorageBackend.SQLITE,
                    sqlite_path=root / "data" / "clink.db",
                ),
            )
            repository = _SQLiteRepository(events)

            def run_installer(
                command: list[str],
                **_kwargs: object,
            ) -> subprocess.CompletedProcess[str]:
                if "install" in command:
                    events.append("switch")
                return subprocess.CompletedProcess(
                    args=["clink-installer"],
                    returncode=0,
                    stdout="version=1.2.3\n",
                    stderr="",
                )

            with (
                patch("apps.node.clink_node.cli._load_valid_settings", return_value=settings),
                patch("apps.node.clink_node.cli.ServiceManager", return_value=_Lifecycle(events)),
                patch("apps.node.clink_node.cli.SQLiteNodeRepository", return_value=repository),
                patch("apps.node.clink_node.cli.subprocess.run", side_effect=run_installer),
            ):
                self.assertEqual(_run_installer(_namespace(root), "install"), 0)

            self.assertEqual(
                [event for event in events if event in {"checkpoint", "switch", "resume"}],
                ["checkpoint", "switch", "resume"],
            )
            checkpoint_index = events.index("checkpoint")
            backup_index = next(
                index
                for index, event in enumerate(events)
                if isinstance(event, tuple) and event[0] == "backup"
            )
            self.assertLess(checkpoint_index, backup_index)
            self.assertLess(backup_index, events.index("switch"))

    def test_sqlite_validation_failure_does_not_invoke_installer(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            events: list[object] = []
            settings = SimpleNamespace(
                paths=SimpleNamespace(data=root / "data"),
                storage=SimpleNamespace(
                    backend=StorageBackend.SQLITE,
                    sqlite_path=root / "data" / "clink.db",
                ),
            )
            repository = _SQLiteRepository(events, fail=RuntimeError("invalid schema"))

            with (
                patch("apps.node.clink_node.cli._load_valid_settings", return_value=settings),
                patch("apps.node.clink_node.cli.ServiceManager", return_value=_Lifecycle(events)),
                patch("apps.node.clink_node.cli.SQLiteNodeRepository", return_value=repository),
                patch("apps.node.clink_node.cli.subprocess.run") as run,
            ):
                with self.assertRaises(RuntimeError):
                    _run_installer(_namespace(root, operation="rollback"), "rollback")

            run.assert_not_called()
            self.assertEqual(events, [("quiesce", "rollback"), "checkpoint", "resume"])

    def test_postgres_rollback_does_not_create_local_sqlite_backup(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            events: list[object] = []
            settings = SimpleNamespace(
                paths=SimpleNamespace(data=root / "data"),
                storage=SimpleNamespace(
                    backend=StorageBackend.POSTGRES,
                    sqlite_path=None,
                ),
            )
            result = subprocess.CompletedProcess(
                args=["clink-installer"],
                returncode=0,
                stdout="version=1.0.0\n",
                stderr="",
            )

            with (
                patch("apps.node.clink_node.cli._load_valid_settings", return_value=settings),
                patch("apps.node.clink_node.cli.ServiceManager", return_value=_Lifecycle(events)),
                patch("apps.node.clink_node.cli.SQLiteNodeRepository") as repository,
                patch("apps.node.clink_node.cli.subprocess.run", return_value=result) as run,
            ):
                self.assertEqual(
                    _run_installer(_namespace(root, operation="rollback"), "rollback"),
                    0,
                )

            repository.assert_not_called()
            run.assert_called_once()
            self.assertEqual(events, [("quiesce", "rollback"), "resume"])


if __name__ == "__main__":
    unittest.main()
