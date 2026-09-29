from __future__ import annotations

import hashlib
import json
import os
import shutil
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from .storage.base import NodeRepository


STATE_SUFFIXES = {".jsonl", ".sqlite", ".sqlite3", ".db"}
IGNORED_PARTS = {
    ".demo_runtime",
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".venv",
    "__pycache__",
    "logs",
    "node_modules",
}


@dataclass(frozen=True)
class MigrationReport:
    source_root: str
    discovered: int
    imported: int
    skipped: int
    manifest_path: Path

    def as_json(self) -> dict[str, object]:
        payload = asdict(self)
        payload["manifest_path"] = str(self.manifest_path)
        return payload


class LegacyArtifactMigrator:
    """Archives legacy state while leaving Core as the money authority."""

    def __init__(
        self,
        *,
        repository: NodeRepository,
        archive_root: Path,
    ) -> None:
        self.repository = repository
        self.archive_root = archive_root.expanduser().resolve()

    def import_root(self, source_root: Path) -> MigrationReport:
        source = source_root.expanduser().resolve()
        if not source.is_dir():
            raise FileNotFoundError(f"legacy root does not exist: {source}")
        artifacts = self._discover(source)
        source_id = hashlib.sha256(str(source).encode()).hexdigest()[:16]
        import_root = self.archive_root / source_id
        import_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(import_root, 0o700)

        records: list[dict[str, object]] = []
        imported = 0
        skipped = 0
        for source_path in artifacts:
            relative = source_path.relative_to(source)
            digest = _sha256(source_path)
            archive_relative = Path("artifacts") / digest / relative
            destination = import_root / archive_relative
            copied = not destination.exists()
            if copied:
                destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                shutil.copy2(source_path, destination)
                os.chmod(destination, 0o600)
                self.repository.append_event(
                    "legacy_artifact_imported",
                    f"{source_id}:{relative.as_posix()}",
                    {
                        "source_app": _source_app(relative),
                        "relative_path": relative.as_posix(),
                        "sha256": digest,
                        "size_bytes": source_path.stat().st_size,
                        "money_source_of_truth": "core",
                    },
                )
                imported += 1
            else:
                skipped += 1
            records.append(
                {
                    "source_app": _source_app(relative),
                    "relative_path": relative.as_posix(),
                    "archive_path": archive_relative.as_posix(),
                    "sha256": digest,
                    "size_bytes": source_path.stat().st_size,
                }
            )

        manifest_path = import_root / "manifest.json"
        manifest = {
            "format": "clink-legacy-import-v1",
            "source_root": str(source),
            "imported_at": datetime.now(UTC).isoformat(),
            "source_of_truth": {
                "identity": "core",
                "funding": "core",
                "policy": "core",
                "audit": "core",
            },
            "artifacts": records,
        }
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.chmod(manifest_path, 0o600)
        return MigrationReport(
            source_root=str(source),
            discovered=len(artifacts),
            imported=imported,
            skipped=skipped,
            manifest_path=manifest_path,
        )

    @staticmethod
    def _discover(source: Path) -> list[Path]:
        found: list[Path] = []
        for path in source.rglob("*"):
            if not path.is_file():
                continue
            relative = path.relative_to(source)
            if any(part in IGNORED_PARTS for part in relative.parts):
                continue
            if path.suffix.lower() not in STATE_SUFFIXES:
                continue
            found.append(path)
        return sorted(found)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_app(relative: Path) -> str:
    parts = relative.parts
    if len(parts) >= 2 and parts[0] == "apps":
        return parts[1]
    return "legacy"
