from __future__ import annotations

import unittest
import json
import subprocess
import sys
from pathlib import Path

from scripts.clink_workspace import (
    load_workspace,
    plan_execution,
    validate_workspace,
)


ROOT = Path(__file__).resolve().parents[1]


class WorkspaceManifestTests(unittest.TestCase):
    def test_workspace_lists_all_imported_apps(self) -> None:
        workspace = load_workspace(ROOT / "clink.workspace.toml")

        self.assertEqual(
            [app.name for app in workspace.apps],
            ["core", "marketplace", "prediction-markets", "node"],
        )

    def test_workspace_paths_and_commands_are_valid(self) -> None:
        workspace = load_workspace(ROOT / "clink.workspace.toml")

        self.assertEqual(validate_workspace(workspace, ROOT), [])

    def test_python_test_apps_use_pytest(self) -> None:
        workspace = load_workspace(ROOT / "clink.workspace.toml")
        apps = {app.name: app for app in workspace.apps}

        self.assertEqual(
            apps["core"].commands["test"],
            ("python3", "-m", "pytest", "-q"),
        )
        self.assertEqual(
            apps["marketplace"].commands["test"],
            ("python3", "-m", "pytest", "-q"),
        )

    def test_root_declares_pytest_development_dependency(self) -> None:
        requirements = (ROOT / "requirements-dev.txt").read_text(
            encoding="utf-8"
        )

        self.assertIn("pytest", requirements)

    def test_execution_plan_uses_app_directory_and_command_array(self) -> None:
        workspace = load_workspace(ROOT / "clink.workspace.toml")

        plan = plan_execution(workspace, ROOT, "core", "status")

        self.assertEqual(plan.cwd, ROOT / "apps/core")
        self.assertEqual(plan.command, ("bash", "run_demo_status.sh"))

    def test_cli_dry_run_returns_machine_readable_plan(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                "scripts/clink_workspace.py",
                "exec",
                "core",
                "status",
                "--dry-run",
            ],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )

        self.assertEqual(
            json.loads(result.stdout),
            {
                "action": "status",
                "app": "core",
                "command": ["bash", "run_demo_status.sh"],
                "cwd": "apps/core",
            },
        )

    def test_makefile_exposes_workspace_and_app_status_targets(self) -> None:
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")

        for target in (
            "doctor:",
            "list:",
            "test-workspace:",
            "test-apps:",
            "install-node:",
            "node-start:",
            "node-stop:",
            "node-status:",
            "node-doctor:",
            "core-status:",
            "marketplace-status:",
            "prediction-markets-status:",
        ):
            self.assertIn(target, makefile)

    def test_workspace_ci_runs_structure_tests_and_python_compile(self) -> None:
        workflow = (
            ROOT / ".github/workflows/workspace.yml"
        ).read_text(encoding="utf-8")

        for command in (
            "make doctor",
            "make test-workspace",
            "make test-node",
            "make test-e2e",
            "make test-apps",
            "python3 -m compileall",
        ):
            self.assertIn(command, workflow)

    def test_unified_node_has_server_and_migration_guides(self) -> None:
        for path in (
            ROOT / "clink.node.server.example.toml",
            ROOT / "docs/deployment/server-profile.md",
            ROOT / "docs/migration/legacy-apps-to-node.md",
        ):
            self.assertTrue(path.is_file(), str(path))


if __name__ == "__main__":
    unittest.main()
