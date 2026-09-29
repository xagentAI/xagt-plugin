from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from clink_node.paths import NodePaths
from clink_node.service_manager import (
    LifecycleLock,
    LifecycleLockBusy,
    ServiceLifecycleError,
    ServiceManager,
)


class _FakeSystemd:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.active = False

    def daemon_reload(self) -> None:
        self.calls.append(("daemon-reload", ""))

    def start(self, unit: str) -> None:
        self.calls.append(("start", unit))
        self.active = True

    def stop(self, unit: str) -> None:
        self.calls.append(("stop", unit))
        self.active = False

    def is_active(self, unit: str) -> bool:
        self.calls.append(("is-active", unit))
        return self.active


class ServiceManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.paths = NodePaths.from_home(Path(self.temporary.name) / ".clink")
        self.paths.ensure()
        self.systemd = _FakeSystemd()
        self.detached: list[str] = []
        self.manager = ServiceManager(
            self.paths,
            systemd=self.systemd,
            detached_runner=lambda: self.detached.append("started"),
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_exclusive_lifecycle_lock_blocks_shared_and_writer(self) -> None:
        lock_path = self.paths.runtime / "lifecycle.lock"
        first = LifecycleLock(lock_path, exclusive=True, blocking=False)
        first.acquire()
        try:
            with self.assertRaises(LifecycleLockBusy):
                LifecycleLock(
                    lock_path,
                    exclusive=False,
                    blocking=False,
                ).acquire()
            with self.assertRaises(LifecycleLockBusy):
                LifecycleLock(
                    lock_path,
                    exclusive=True,
                    blocking=False,
                ).acquire()
        finally:
            first.release()

    def test_quiesce_is_atomic_and_blocks_new_service_start(self) -> None:
        self.manager.quiesce(reason="upgrade")
        sentinel = self.paths.runtime / "maintenance.quiesced"
        self.assertTrue(sentinel.is_file())
        self.assertIn("upgrade", sentinel.read_text(encoding="utf-8"))
        with self.assertRaises(ServiceLifecycleError):
            self.manager.start(detach=True)
        self.manager.resume()
        self.manager.start(detach=True)
        self.assertEqual(self.detached, ["started"])

    def test_quiesce_sentinel_requires_owner_only_regular_file(self) -> None:
        sentinel = self.paths.runtime / "maintenance.quiesced"
        sentinel.write_text("maintenance", encoding="utf-8")
        sentinel.chmod(0o644)
        with self.assertRaises(ServiceLifecycleError):
            self.manager.is_quiesced()
        sentinel.unlink()
        target = self.paths.runtime / "sentinel-target"
        target.write_text("maintenance", encoding="utf-8")
        sentinel.symlink_to(target)
        with self.assertRaises(ServiceLifecycleError):
            self.manager.is_quiesced()

    def test_quiesce_fails_fast_when_node_holds_shared_lifecycle_lock(self) -> None:
        lock = LifecycleLock(
            self.paths.runtime / "lifecycle.lock",
            exclusive=False,
            blocking=False,
        ).acquire()
        try:
            with self.assertRaisesRegex(ServiceLifecycleError, "stop"):
                self.manager.quiesce(reason="upgrade")
        finally:
            lock.release()

    def test_systemd_and_detach_are_mutually_exclusive(self) -> None:
        with self.assertRaises(ServiceLifecycleError):
            self.manager.start(detach=True, systemd=True)
        self.manager.start(systemd=True)
        self.assertIn(("start", "clink-node.service"), self.systemd.calls)

    def test_install_does_not_enable_or_start_systemd(self) -> None:
        target = Path(self.temporary.name) / "clink-node.service"
        self.manager.install_unit(target)
        self.assertTrue(target.is_file())
        names = [name for name, _value in self.systemd.calls]
        self.assertEqual(names, [])

    def test_service_status_and_uninstall_are_explicit(self) -> None:
        self.manager.install_unit(
            Path(self.temporary.name) / "clink-node.service"
        )
        self.assertFalse(self.manager.status(systemd=True).active)
        self.manager.start(systemd=True)
        self.assertTrue(self.manager.status(systemd=True).active)
        self.manager.stop(systemd=True)
        self.assertFalse(self.manager.status(systemd=True).active)
        self.manager.uninstall(
            Path(self.temporary.name) / "clink-node.service"
        )
        self.assertFalse(
            (Path(self.temporary.name) / "clink-node.service").exists()
        )
        self.assertNotIn(("enable", "clink-node.service"), self.systemd.calls)


if __name__ == "__main__":
    unittest.main()
