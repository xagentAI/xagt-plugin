from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class InstallClinkNodeTests(unittest.TestCase):
    def test_dry_run_builds_local_first_install_plan(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                "scripts/install_clink_node.py",
                "--dry-run",
                "--profile",
                "personal",
                "--venv",
                "/tmp/clink-test-venv",
                "--clink-home",
                "/tmp/clink-test-home",
            ],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )

        plan = json.loads(result.stdout)
        self.assertEqual(plan["profile"], "personal")
        self.assertEqual(
            plan["clink_home"],
            str(Path("/tmp/clink-test-home").resolve()),
        )
        self.assertEqual(
            plan["commands"][0],
            [
                sys.executable,
                "-m",
                "venv",
                str(Path("/tmp/clink-test-venv").resolve()),
            ],
        )
        self.assertIn(
            [
                str(
                    Path("/tmp/clink-test-venv/bin/python").resolve()
                ),
                "-m",
                "pip",
                "install",
                "-e",
                str(ROOT / "apps/node"),
            ],
            plan["commands"],
        )
        self.assertEqual(
            plan["commands"][-1],
            [
                str(
                    Path("/tmp/clink-test-venv/bin/python").resolve()
                ),
                "-m",
                "clink_node",
                "init",
                "--profile",
                "personal",
            ],
        )


if __name__ == "__main__":
    unittest.main()
