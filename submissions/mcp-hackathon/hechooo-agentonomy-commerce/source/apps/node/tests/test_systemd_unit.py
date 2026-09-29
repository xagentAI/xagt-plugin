from __future__ import annotations

import unittest
from pathlib import Path


UNIT = (
    Path(__file__).resolve().parents[3]
    / "packaging/linux/systemd/clink.service"
)


class SystemdUnitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.assertTrue(UNIT.is_file(), f"missing unit: {UNIT}")
        self.content = UNIT.read_text(encoding="utf-8")

    def test_unit_uses_verified_launcher_and_restrictive_sandbox(self) -> None:
        required = (
            "Type=simple",
            "ExecStart=%h/.clink/current/payload/bin/clink-launcher _run --systemd",
            "NoNewPrivileges=true",
            "PrivateTmp=true",
            "ProtectSystem=strict",
            "ProtectHome=read-only",
            "ReadWritePaths=%h/.clink",
            "LockPersonality=true",
            "MemoryDenyWriteExecute=true",
            "RestrictSUIDSGID=true",
            "UMask=0077",
        )
        for line in required:
            with self.subTest(line=line):
                self.assertIn(line, self.content)

    def test_unit_does_not_auto_enable_or_start(self) -> None:
        self.assertNotIn("WantedBy=", self.content)
        self.assertNotIn("systemctl enable", self.content)
        self.assertNotIn("systemctl start", self.content)

    def test_unit_does_not_run_as_root_or_expose_extra_capabilities(self) -> None:
        # A user unit already inherits the installing user's identity; an
        # explicit User= directive is invalid/meaningless in this context.
        self.assertNotIn("User=", self.content)
        self.assertIn("CapabilityBoundingSet=", self.content)
        self.assertIn("RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6", self.content)


if __name__ == "__main__":
    unittest.main()
