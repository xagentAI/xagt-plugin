from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from apps.node.clink_node.migration import LegacyArtifactMigrator
from apps.node.clink_node.storage.sqlite import SQLiteNodeRepository


class LegacyArtifactMigratorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.repository = SQLiteNodeRepository(self.root / "node.db")
        self.repository.migrate()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_archives_known_state_without_exposing_contents(self) -> None:
        source = self.root / "legacy"
        state = (
            source
            / "apps"
            / "prediction-markets"
            / "services"
            / "execution_service"
            / "executions.jsonl"
        )
        state.parent.mkdir(parents=True)
        state.write_text(
            '{"execution_id":"exec_1","secret":"do-not-log"}\n',
            encoding="utf-8",
        )

        report = LegacyArtifactMigrator(
            repository=self.repository,
            archive_root=self.root / "imports",
        ).import_root(source)

        self.assertEqual(report.imported, 1)
        self.assertEqual(report.skipped, 0)
        manifest = json.loads(report.manifest_path.read_text())
        self.assertEqual(manifest["source_of_truth"]["funding"], "core")
        self.assertEqual(len(manifest["artifacts"]), 1)
        self.assertNotIn("do-not-log", json.dumps(manifest))
        archived = report.manifest_path.parent / manifest["artifacts"][0]["archive_path"]
        self.assertEqual(archived.read_text(), state.read_text())
        self.assertEqual(archived.stat().st_mode & 0o777, 0o600)

        events = self.repository.pending_events()
        self.assertEqual(events[0]["event_type"], "legacy_artifact_imported")
        self.assertNotIn("do-not-log", json.dumps(events))

    def test_second_import_is_idempotent_for_unchanged_artifact(self) -> None:
        source = self.root / "legacy"
        state = (
            source
            / "apps"
            / "core"
            / "services"
            / "funding_service"
            / "funding_ledger.sqlite3"
        )
        state.parent.mkdir(parents=True)
        state.write_bytes(b"sqlite-state")
        migrator = LegacyArtifactMigrator(
            repository=self.repository,
            archive_root=self.root / "imports",
        )

        first = migrator.import_root(source)
        second = migrator.import_root(source)

        self.assertEqual(first.imported, 1)
        self.assertEqual(second.imported, 0)
        self.assertEqual(second.skipped, 1)
        self.assertEqual(len(self.repository.pending_events()), 1)

    def test_ignores_logs_dependencies_and_unknown_files(self) -> None:
        source = self.root / "legacy"
        ignored = (
            source
            / "apps"
            / "core"
            / ".demo_runtime"
            / "logs"
            / "funding.jsonl"
        )
        ignored.parent.mkdir(parents=True)
        ignored.write_text("{}\n")
        unknown = source / "README.md"
        unknown.write_text("not state")

        report = LegacyArtifactMigrator(
            repository=self.repository,
            archive_root=self.root / "imports",
        ).import_root(source)

        self.assertEqual(report.discovered, 0)
        self.assertEqual(report.imported, 0)


if __name__ == "__main__":
    unittest.main()
