from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


class ManagedScriptContractTests(unittest.TestCase):
    def test_all_legacy_runners_honor_node_managed_environment(self) -> None:
        for relative in (
            "apps/core/run_demo.sh",
            "apps/marketplace/run_demo.sh",
            "apps/prediction-markets/run_demo.sh",
        ):
            script = (ROOT / relative).read_text(encoding="utf-8")
            with self.subTest(script=relative):
                self.assertIn("CLINK_NODE_MANAGED", script)

    def test_managed_modules_run_their_own_migrations(self) -> None:
        core_script = (ROOT / "apps/core/run_demo.sh").read_text(
            encoding="utf-8"
        )
        script = (ROOT / "apps/marketplace/run_demo.sh").read_text(
            encoding="utf-8"
        )

        self.assertIn("-m alembic upgrade head", core_script)
        self.assertIn("-m alembic upgrade head", script)
        self.assertNotIn(
            'if [ "${CLINK_NODE_MANAGED:-0}" != "1" ]; then\n'
            '  "$PYTHON" -m alembic upgrade head\n'
            "fi",
            script,
        )

    def test_managed_modules_use_distinct_alembic_version_tables(
        self,
    ) -> None:
        expectations = {
            "apps/core/migrations/env.py": "alembic_version_core",
            "apps/marketplace/migrations/env.py": (
                "alembic_version_marketplace"
            ),
        }

        for relative, version_table in expectations.items():
            migration_environment = (ROOT / relative).read_text(
                encoding="utf-8"
            )
            with self.subTest(relative=relative):
                self.assertIn("CLINK_NODE_MANAGED", migration_environment)
                self.assertIn(version_table, migration_environment)

    def test_marketplace_managed_startup_waits_for_liveness(self) -> None:
        script = (ROOT / "apps/marketplace/run_demo.sh").read_text(
            encoding="utf-8"
        )

        self.assertIn('startup_path="/livez"', script)
        self.assertIn('startup_path="/healthz"', script)
        self.assertIn('"$registry_url$startup_path"', script)

    def test_all_legacy_runners_exit_after_termination_cleanup(
        self,
    ) -> None:
        core_script = (ROOT / "apps/core/run_demo.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn("trap 'cleanup; exit 130' INT", core_script)
        self.assertIn("trap 'cleanup; exit 143' TERM", core_script)

        for relative in (
            "apps/marketplace/run_demo.sh",
            "apps/prediction-markets/run_demo.sh",
        ):
            script = (ROOT / relative).read_text(encoding="utf-8")
            with self.subTest(script=relative):
                self.assertIn("terminate_runner()", script)
                self.assertIn("trap terminate_runner INT TERM", script)
                self.assertIn("cleanup\n  exit 0", script)


if __name__ == "__main__":
    unittest.main()
