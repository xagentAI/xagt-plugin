"""Synchronous JSON-line client for the isolated local Core worker."""

from __future__ import annotations

import json
import os
from pathlib import Path
import selectors
import subprocess
import sys
import threading
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
WORKER = ROOT / "examples" / "commerce" / "core_worker.py"


class CoreBridge:
    """Expose the Core service composition without importing Core in Marketplace."""

    def __init__(self, state_dir: Path, *, persistent: bool = False):
        self.state_dir = Path(state_dir).expanduser().resolve()
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.persistent = persistent
        self.process: subprocess.Popen[str] | None = None
        self._lock = threading.Lock()
        self._next_id = 0
        self._broken: str | None = None

    def __enter__(self) -> "CoreBridge":
        try:
            self._start()
            if self.persistent:
                # Persistent startup errors are reported by the worker before it
                # accepts requests, so a context cannot expose half-initialized
                # state to its caller.
                self._call("health")
            return self
        except Exception:
            self.close()
            raise

    def __exit__(self, _exc_type, _exc_value, _traceback) -> None:
        self.close()

    def _start(self) -> None:
        if self._broken is not None:
            raise RuntimeError(f"local Core bridge is broken: {self._broken}")
        if self.process is not None:
            return
        safe_keys = {"PATH", "SYSTEMROOT", "TMPDIR", "LANG", "LC_ALL"}
        env = {key: value for key, value in os.environ.items() if key in safe_keys}
        env["PYTHONPATH"] = str(ROOT / "apps" / "core")
        env["PYTHONUNBUFFERED"] = "1"
        arguments = [sys.executable, str(WORKER), str(self.state_dir)]
        if self.persistent:
            arguments.append("--persistent")
        self.process = subprocess.Popen(
            arguments,
            cwd=ROOT,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=sys.stderr,
            text=True,
            bufsize=1,
        )

    def _call(self, method: str, params: dict[str, Any] | None = None) -> Any:
        with self._lock:
            self._start()
            assert self.process is not None
            if self.process.poll() is not None:
                message = "local Core worker exited before the request"
                self._mark_broken(message)
                raise RuntimeError(message)
            self._next_id += 1
            request = {
                "id": self._next_id,
                "method": method,
                "params": params or {},
            }
            assert self.process.stdin is not None
            assert self.process.stdout is not None
            try:
                self.process.stdin.write(
                    json.dumps(request, default=str, separators=(",", ":")) + "\n"
                )
                self.process.stdin.flush()
            except (BrokenPipeError, OSError) as exc:
                message = "local Core worker channel is unavailable"
                self._mark_broken(message)
                raise RuntimeError(message) from exc
            with selectors.DefaultSelector() as selector:
                try:
                    selector.register(self.process.stdout, selectors.EVENT_READ)
                    ready = selector.select(timeout=45)
                except (OSError, ValueError) as exc:
                    message = "local Core worker channel is unavailable"
                    self._mark_broken(message)
                    raise RuntimeError(message) from exc
                if not ready:
                    message = (
                        "local Core outcome is unknown; inspect the existing "
                        "reservation before retrying"
                    )
                    self._mark_broken(message)
                    raise TimeoutError(message)
            line = self.process.stdout.readline()
            if not line:
                message = "local Core worker stopped before replying"
                self._mark_broken(message)
                raise RuntimeError(message)
            try:
                response = json.loads(line)
            except json.JSONDecodeError as exc:
                message = "local Core worker returned invalid protocol data"
                self._mark_broken(message)
                raise RuntimeError(message) from exc
            if response.get("id") != request["id"]:
                if response.get("id") is None and response.get("ok") is False:
                    error = response.get("error") or {}
                    message = (
                        error.get("message")
                        if isinstance(error, dict)
                        else str(error)
                    ) or "local Core worker failed to start"
                    self._mark_broken(message)
                    raise RuntimeError(message)
                message = "local Core worker returned a mismatched request id"
                self._mark_broken(message)
                raise RuntimeError(message)
            if response.get("ok") is not True:
                error = response.get("error") or {}
                if isinstance(error, dict):
                    message = error.get("message") or "local Core operation failed"
                else:
                    message = str(error)
                raise RuntimeError(message)
            return response.get("result")

    def _mark_broken(self, reason: str) -> None:
        self._broken = reason
        process, self.process = self.process, None
        if process is None:
            return
        if process.stdin is not None:
            try:
                process.stdin.close()
            except (BrokenPipeError, OSError):
                pass
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        if process.stdout is not None:
            process.stdout.close()

    def close(self) -> None:
        process, self.process = self.process, None
        if process is None:
            return
        if process.stdin is not None:
            try:
                process.stdin.close()
            except (BrokenPipeError, OSError):
                pass
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        if process.stdout is not None:
            process.stdout.close()

    def resolve_authorization(self, payload: dict[str, Any]) -> dict:
        return self._call("resolve_authorization", payload)

    def create_account_session(self, user_id: str) -> dict:
        return self._call("create_account_session", {"user_id": user_id})

    def create_action(self, payload: dict[str, Any]) -> dict:
        return self._call("create_action", payload)

    def evaluate_policy(self, payload: dict[str, Any]) -> dict:
        return self._call("evaluate_policy", payload)

    def update_action(self, action_id: str, payload: dict[str, Any]) -> dict:
        return self._call(
            "update_action", {"action_id": action_id, "payload": payload}
        )

    def audit(self, payload: dict[str, Any]) -> dict:
        return self._call("audit", payload)

    def funding_readiness(self) -> dict:
        return self._call("funding_readiness")

    def reserve(self, payload: dict[str, Any]) -> dict:
        return self._call("reserve", payload)

    def settle(self, reservation_id: str, payload: dict[str, Any]) -> dict:
        return self._call(
            "settle", {"reservation_id": reservation_id, "payload": payload}
        )

    def reconcile(self, reservation_id: str) -> dict:
        return self._call("reconcile", {"reservation_id": reservation_id})

    def finalize(self, reservation_id: str, payload: dict[str, Any]) -> dict:
        return self._call(
            "finalize", {"reservation_id": reservation_id, "payload": payload}
        )

    def reservation(self, reservation_id: str) -> dict | None:
        return self._call("reservation", {"reservation_id": reservation_id})

    def release(self, reservation_id: str, reason: str) -> dict:
        return self._call(
            "release", {"reservation_id": reservation_id, "reason": reason}
        )

    def health(self) -> dict:
        return self._call("health")

    def snapshot(self) -> dict:
        return self._call("snapshot")

    def revoke(self) -> dict:
        return self._call("revoke")
