"""Alembic loader for the Hosted finality compensation revision."""

from __future__ import annotations

from pathlib import Path
from runpy import run_path
from typing import Any, Sequence


_SOURCE = (
    Path(__file__).resolve().parents[1]
    / "20260901_0008_hosted_finality_compensation.py"
)
_REVISION: dict[str, Any] = run_path(str(_SOURCE))

revision: str = _REVISION["revision"]
down_revision: str | None = _REVISION["down_revision"]
branch_labels: Sequence[str] | None = _REVISION["branch_labels"]
depends_on: Sequence[str] | None = _REVISION["depends_on"]


def upgrade() -> None:
    _REVISION["upgrade"]()


def downgrade() -> None:
    _REVISION["downgrade"]()
