from __future__ import annotations

import os
import stat
import tempfile
import unittest
from pathlib import Path

from clink_node.instance_lock import InstanceLock, InstanceLockError


class InstanceLockTests(unittest.TestCase):
    def test_lock_is_exclusive_and_owner_only(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "runtime" / "node.lock"
            path.parent.mkdir(mode=0o700)
            first = InstanceLock(path)
            second = InstanceLock(path)
            first.acquire()
            try:
                with self.assertRaises(InstanceLockError):
                    second.acquire()
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
                self.assertIn(str(os.getpid()), path.read_text(encoding="ascii"))
            finally:
                first.release()

            second.acquire()
            second.release()

    def test_lock_rejects_symlink_and_non_regular_lock_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "target"
            target.write_text("not-a-lock", encoding="ascii")
            link = root / "node.lock"
            link.symlink_to(target)
            with self.assertRaises(PermissionError):
                InstanceLock(link).acquire()

            link.unlink()
            link.mkdir(mode=0o700)
            with self.assertRaises(PermissionError):
                InstanceLock(link).acquire()

    def test_release_does_not_remove_a_replaced_lock_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "node.lock"
            lock = InstanceLock(path)
            lock.acquire()
            replacement = path.with_name("replacement")
            replacement.write_text("replacement", encoding="ascii")
            path.unlink()
            path.symlink_to(replacement)
            lock.release()
            self.assertTrue(path.is_symlink())
            self.assertEqual(path.read_text(encoding="ascii"), "replacement")


if __name__ == "__main__":
    unittest.main()
