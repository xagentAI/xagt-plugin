"""Exercise the independent CLI against real HTTP, with no persistent keys or DB."""

import base64
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[2]


def test_signed_deployment_over_real_uvicorn():
    # Container test contexts deliberately exclude Git metadata; conftest supplies a test SHA.
    commit = (subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
              if (ROOT / ".git").exists() else os.environ["GIT_COMMIT"])
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    env = {**os.environ, "DATABASE_URL": "sqlite://", "GIT_COMMIT": commit,
           "PROJECT_SLUG": "apivouch", "PUBLIC_BASE_URL": base, "REQUIRE_SIGNED_RECEIPTS": "true",
           "RECEIPT_SIGNING_KEY_ID": "disposable-integration",
           "RECEIPT_SIGNING_PRIVATE_KEY_B64": base64.b64encode(Ed25519PrivateKey.generate().private_bytes_raw()).decode()}
    process = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--app-dir", "backend",
                                "--host", "127.0.0.1", "--port", str(port), "--no-access-log", "--log-level", "critical"],
                               cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        deadline = time.monotonic() + 20
        with httpx.Client(trust_env=False, timeout=1) as client:
            while True:
                assert process.poll() is None, "Disposable Uvicorn exited before readiness"
                try:
                    if client.get(base + "/ready").status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                assert time.monotonic() < deadline, "Disposable Uvicorn readiness timed out"
                time.sleep(0.1)
        result = subprocess.run([sys.executable, "scripts/verify_deployment.py", "--base-url", base,
                                 "--expected-commit", commit, "--mode", "deterministic"], cwd=ROOT,
                                capture_output=True, text=True, timeout=60, check=False)
        assert result.stderr == ""
        report = json.loads(result.stdout)
        assert result.returncode == 0, report
        assert "receipt.signature" in report["checks"]
        assert "proof.exact_urls" in report["checks"]
        assert report["live_verified"] is False
        print(result.stdout.strip())
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
