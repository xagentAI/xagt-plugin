from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
NODE_TEST = ROOT / "tests" / "frontend" / "console_behavior.test.cjs"


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is unavailable")
def test_console_frontend_workflows_execute_successfully():
    result = subprocess.run(
        ["node", "--test", str(NODE_TEST)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
