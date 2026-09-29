from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


class SharedDatabaseMigrationTests(unittest.TestCase):
    def test_core_and_marketplace_migrate_one_node_database(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = (
                Path(temporary_directory) / "clink-node.sqlite3"
            )
            database_url = f"sqlite+pysqlite:///{database_path}"
            environment = {
                **os.environ,
                "CLINK_NODE_MANAGED": "1",
                "CLINK_FUNDING_DATABASE_URL": database_url,
                "MARKETPLACE_DATABASE_URL": database_url,
            }

            self._upgrade(ROOT / "apps/core", environment)
            self._upgrade(ROOT / "apps/marketplace", environment)

            with sqlite3.connect(database_path) as connection:
                versions = {
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master "
                        "WHERE type = 'table' "
                        "AND name LIKE 'alembic_version_%'"
                    )
                }
                table_count = connection.execute(
                    "SELECT COUNT(*) FROM sqlite_master "
                    "WHERE type = 'table'"
                ).fetchone()[0]

            self.assertEqual(
                versions,
                {
                    "alembic_version_core",
                    "alembic_version_marketplace",
                },
            )
            self.assertGreaterEqual(table_count, 32)

    def _upgrade(
        self,
        application_root: Path,
        environment: dict[str, str],
    ) -> None:
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=application_root,
            env=environment,
            check=True,
            capture_output=True,
            text=True,
        )


if __name__ == "__main__":
    unittest.main()
