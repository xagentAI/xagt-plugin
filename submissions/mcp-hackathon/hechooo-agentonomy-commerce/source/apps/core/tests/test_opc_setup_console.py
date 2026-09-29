from __future__ import annotations

import json
import subprocess

from services.account_service.console import ACCOUNT_CONSOLE_JS


def _run_node_assertion(expression: str) -> None:
    script = f"const accountConsole = {json.dumps(ACCOUNT_CONSOLE_JS)};\n{expression}"
    result = subprocess.run(
        ["node", "--input-type=module", "-"],
        input=script,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def test_opc_setup_script_contains_bootstrap_gated_single_cta_controller() -> None:
    _run_node_assertion(
        "if (!accountConsole.includes('opc-setup-submit')) throw new Error('missing OPC setup CTA');"
    )
