"""Run one operator-only Hosted execution rehearsal against Core.

The canary deliberately has no chain or Facilitator client.  Core owns the
reservation, Hosted execution, watcher evidence, and budget settlement.  This
script only reads and reconciles one existing reservation and has one guarded
settle request.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import stat
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


AMOY_NETWORK = "eip155:80002"
AMOY_USDC_ADDRESS = "0x41e94eb019c0762f9bfcf9fb1e58725bfb0e7582"
CORE_TOKEN_ENV = "CLINK_CORE_INTERNAL_API_TOKEN"
_EVM_ADDRESS = re.compile(r"^0x[0-9a-fA-F]{40}$")
_ATOMIC_AMOUNT = re.compile(r"^[1-9][0-9]*$")
_TX_HASH = re.compile(r"^0x[0-9a-fA-F]{64}$")
_OPAQUE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")
_MAX_RESPONSE_BYTES = 1_048_576
_MAX_TIMEOUT_SECONDS = 600.0
_MAX_POLL_SECONDS = 60.0


class CanaryError(RuntimeError):
    """A bounded, safe-to-display canary error."""


class CoreHttpError(CanaryError):
    def __init__(self, status: int):
        super().__init__(f"Core returned HTTP {status}")
        self.status = status


@dataclass(frozen=True)
class Journal:
    reservation_id: str
    idempotency_key: str
    phase: str


RequestJson = Callable[[str, str, dict[str, Any] | None, dict[str, str]], dict[str, Any]]


class _NoRedirect(HTTPRedirectHandler):
    """Refuse redirects before the Core bearer token can leave its origin."""

    def redirect_request(
        self,
        req: object,
        fp: object,
        code: int,
        msg: str,
        headers: object,
        newurl: str,
    ) -> None:
        del req, fp, code, msg, headers, newurl
        return None


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise CanaryError("Core returned duplicate JSON fields")
        result[key] = value
    return result


def _normal_address(value: object, *, field: str) -> str:
    if not isinstance(value, str) or _EVM_ADDRESS.fullmatch(value) is None:
        raise CanaryError(f"{field} is invalid")
    return value.lower()


def _normal_amount(value: object, *, field: str) -> str:
    if not isinstance(value, str) or _ATOMIC_AMOUNT.fullmatch(value) is None:
        raise CanaryError(f"{field} is invalid")
    return value


def _normal_origin(value: str) -> str:
    if not isinstance(value, str):
        raise CanaryError("core origin is invalid")
    origin = value.strip().rstrip("/")
    parsed = urlsplit(origin)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise CanaryError("core origin must be an HTTP(S) origin")
    if parsed.scheme != "https" and (parsed.hostname or "").lower() not in {
        "localhost",
        "127.0.0.1",
        "::1",
    }:
        raise CanaryError("core origin must use HTTPS outside loopback")
    return origin


def _request_json(
    method: str,
    url: str,
    payload: dict[str, Any] | None,
    headers: dict[str, str],
    *,
    timeout_seconds: float,
) -> dict[str, Any]:
    body = None if payload is None else json.dumps(payload, separators=(",", ":")).encode()
    request = Request(url, data=body, headers=headers, method=method)
    try:
        with build_opener(_NoRedirect()).open(
            request, timeout=timeout_seconds
        ) as response:
            raw = response.read(_MAX_RESPONSE_BYTES + 1)
    except HTTPError as exc:
        raise CoreHttpError(int(exc.code)) from None
    except (URLError, OSError, TimeoutError):
        raise CanaryError("Core request was unavailable") from None
    if not isinstance(raw, bytes) or len(raw) > _MAX_RESPONSE_BYTES:
        raise CanaryError("Core returned an invalid response")
    try:
        decoded = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object)
    except (UnicodeError, TypeError, ValueError, RecursionError):
        raise CanaryError("Core returned invalid JSON") from None
    if not isinstance(decoded, dict):
        raise CanaryError("Core returned an invalid reservation projection")
    return decoded


def _journal_mode(path: Path) -> int:
    try:
        mode = stat.S_IMODE(path.stat().st_mode)
    except FileNotFoundError:
        return 0
    if path.is_symlink() or mode != 0o600:
        raise CanaryError("canary journal must be a non-symlink owner-only 0600 file")
    return mode


def _acquire_journal_lock(path: Path) -> int:
    """Acquire the one non-blocking process lock for this canary journal."""

    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock_path = path.with_name(f"{path.name}.lock")
    flags = os.O_RDWR | os.O_CREAT
    if not hasattr(os, "O_NOFOLLOW"):
        raise CanaryError("safe canary journal locking is unavailable")
    flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(lock_path, flags, 0o600)
    except OSError:
        raise CanaryError("canary journal lock is invalid") from None
    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or stat.S_IMODE(metadata.st_mode) != 0o600
        ):
            raise CanaryError("canary journal lock must be owner-only 0600")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise CanaryError("another canary process already owns this journal") from None
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _release_journal_lock(descriptor: int) -> None:
    try:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
    finally:
        os.close(descriptor)


def _load_journal(path: Path) -> Journal | None:
    if not path.exists():
        return None
    _journal_mode(path)
    try:
        with path.open(encoding="utf-8") as handle:
            payload = json.load(handle, object_pairs_hook=_unique_object)
    except (OSError, UnicodeError, TypeError, ValueError, RecursionError):
        raise CanaryError("canary journal is invalid") from None
    if not isinstance(payload, dict):
        raise CanaryError("canary journal is invalid")
    reservation_id = payload.get("reservation_id")
    idempotency_key = payload.get("idempotency_key")
    phase = payload.get("phase")
    if (
        not isinstance(reservation_id, str)
        or not reservation_id
        or not isinstance(idempotency_key, str)
        or not idempotency_key
        or phase not in {"dispatching", "settle_dispatched", "reconciling", "settled"}
        or set(payload) != {"version", "reservation_id", "idempotency_key", "phase"}
        or payload.get("version") != 1
    ):
        raise CanaryError("canary journal is invalid")
    return Journal(reservation_id, idempotency_key, phase)


def _save_journal(path: Path, journal: Journal) -> None:
    """Atomically write the dispatch marker before the settle POST."""

    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    payload = {
        "version": 1,
        "reservation_id": journal.reservation_id,
        "idempotency_key": journal.idempotency_key,
        "phase": journal.phase,
    }
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(temporary, flags, 0o600)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                descriptor = -1
                json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, path)
            os.chmod(path, 0o600)
            directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
            directory_descriptor = os.open(path.parent, directory_flags)
            try:
                os.fsync(directory_descriptor)
            finally:
                os.close(directory_descriptor)
        finally:
            if descriptor >= 0:
                os.close(descriptor)
    except FileExistsError:
        raise CanaryError("canary journal write collided; inspect before retrying") from None
    except OSError:
        raise CanaryError("canary journal could not be written safely") from None
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            pass


def _reservation_projection(payload: dict[str, Any]) -> dict[str, Any]:
    if "reservation" in payload and isinstance(payload["reservation"], dict):
        return payload["reservation"]
    return payload


def _executor_candidates(row: dict[str, Any]) -> list[str]:
    candidates: list[str] = []
    for field in ("executor_contract", "spender_address", "executor"):
        value = row.get(field)
        if isinstance(value, str):
            candidates.append(value)
    hosted_response = row.get("hosted_response")
    if isinstance(hosted_response, dict):
        for field in ("executor_contract", "executor", "spender_address"):
            value = hosted_response.get(field)
            if isinstance(value, str):
                candidates.append(value)
    return candidates


def _validate_scope(
    row: dict[str, Any],
    *,
    reservation_id: str,
    expected_payee: str,
    expected_amount: str,
    expected_executor: str,
) -> str:
    if row.get("reservation_id") != reservation_id:
        raise CanaryError("reservation identity does not match the canary")
    idempotency_key = row.get("idempotency_key")
    if not isinstance(idempotency_key, str) or not idempotency_key:
        raise CanaryError("reservation idempotency identity is missing")
    if row.get("network", row.get("chain")) != AMOY_NETWORK:
        raise CanaryError("reservation network is not Polygon Amoy")
    token = row.get("token_address")
    if not isinstance(token, str) or token.lower() != AMOY_USDC_ADDRESS:
        raise CanaryError("reservation token is not canonical Amoy USDC")
    if _normal_amount(row.get("amount_atomic"), field="reservation amount") != expected_amount:
        raise CanaryError("reservation amount does not match the canary")
    destination = row.get("destination", row.get("pay_to"))
    if _normal_address(destination, field="reservation payee") != expected_payee:
        raise CanaryError("reservation payee does not match the canary")
    resource = row.get("resource")
    if not isinstance(resource, str) or not resource.strip():
        raise CanaryError("reservation resource is missing")
    executor_values = _executor_candidates(row)
    if not executor_values:
        raise CanaryError("reservation executor scope is missing")
    try:
        normalized_executors = {
            _normal_address(value, field="reservation executor")
            for value in executor_values
        }
    except CanaryError:
        raise
    if normalized_executors != {expected_executor}:
        raise CanaryError("reservation executor does not match the canary")
    return idempotency_key


def _exact_business_intent(row: dict[str, Any]) -> dict[str, str]:
    """Build Core's exact business intent from the already validated row."""

    # ``resource`` is deliberately checked at the Core reservation boundary
    # above.  The x402 exact envelope itself is the five-field business
    # payment shape accepted by Core; the resource stays Core-owned and is
    # never supplied by the operator as an independent fact.
    return {
        "scheme": "exact",
        "network": str(row["network"]),
        "asset": str(row["token_address"]),
        "amount_atomic": str(row["amount_atomic"]),
        "pay_to": str(row["destination"]),
    }


def _success_evidence(
    row: dict[str, Any],
    *,
    reservation_id: str,
    expected_idempotency_key: str,
    expected_payee: str,
    expected_amount: str,
    expected_executor: str,
) -> bool:
    if row.get("state") not in {"settled", "finalized"}:
        return False
    if row.get("budget_accounting_state") != "settled":
        return False
    try:
        observed_idempotency_key = _validate_scope(
            row,
            reservation_id=reservation_id,
            expected_payee=expected_payee,
            expected_amount=expected_amount,
            expected_executor=expected_executor,
        )
        if observed_idempotency_key != expected_idempotency_key:
            return False
    except CanaryError:
        return False
    tx_hash = row.get("tx_hash")
    receipt_id = row.get("receipt_id")
    execution_id = row.get("hosted_execution_id")
    receipt = row.get("receipt")
    if receipt is not None and not isinstance(receipt, dict):
        return False
    nested_tx_hash = receipt.get("tx_hash") if isinstance(receipt, dict) else None
    nested_receipt_id = receipt.get("receipt_id") if isinstance(receipt, dict) else None
    metadata = receipt.get("metadata") if isinstance(receipt, dict) else None
    if metadata is not None and not isinstance(metadata, dict):
        return False
    nested_execution_id = (
        metadata.get("hosted_execution_id") if isinstance(metadata, dict) else None
    )
    if (
        not isinstance(tx_hash, str)
        or _TX_HASH.fullmatch(tx_hash) is None
        or not isinstance(receipt_id, str)
        or _OPAQUE_ID.fullmatch(receipt_id) is None
        or not isinstance(execution_id, str)
        or _OPAQUE_ID.fullmatch(execution_id) is None
    ):
        return False
    if nested_tx_hash is not None and (
        not isinstance(nested_tx_hash, str)
        or _TX_HASH.fullmatch(nested_tx_hash) is None
        or nested_tx_hash.lower() != tx_hash.lower()
    ):
        return False
    if nested_receipt_id is not None and (
        not isinstance(nested_receipt_id, str)
        or _OPAQUE_ID.fullmatch(nested_receipt_id) is None
        or nested_receipt_id != receipt_id
    ):
        return False
    if nested_execution_id is not None and (
        not isinstance(nested_execution_id, str)
        or _OPAQUE_ID.fullmatch(nested_execution_id) is None
        or nested_execution_id != execution_id
    ):
        return False
    return bool(
        isinstance(row.get("hosted_watcher_evidence_hash"), str)
        and _TX_HASH.fullmatch(row["hosted_watcher_evidence_hash"]) is not None
    )


def run_canary(
    *,
    core_origin: str,
    reservation_id: str,
    expected_payee: str,
    expected_amount_atomic: str,
    expected_executor: str,
    journal_path: Path | str,
    timeout_seconds: float = 120.0,
    poll_seconds: float = 2.0,
    submit_once: bool = False,
    request_json: RequestJson | None = None,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    emit: Callable[[str], None] = print,
) -> int:
    """Inspect one reservation and, with ``submit_once``, dispatch one settle.

    The Core token is intentionally read only from ``CLINK_CORE_INTERNAL_API_TOKEN``.
    ``request_json`` exists solely for deterministic tests and receives a path,
    not a Facilitator or chain endpoint.
    """

    try:
        origin = _normal_origin(core_origin)
        if not isinstance(reservation_id, str) or not reservation_id:
            raise CanaryError("reservation id is invalid")
        expected_payee = _normal_address(expected_payee, field="expected payee")
        expected_executor = _normal_address(expected_executor, field="expected executor")
        expected_amount_atomic = _normal_amount(
            expected_amount_atomic, field="expected amount"
        )
        if (
            not isinstance(timeout_seconds, (int, float))
            or timeout_seconds <= 0
            or timeout_seconds > _MAX_TIMEOUT_SECONDS
        ):
            raise CanaryError("timeout must be positive")
        if (
            not isinstance(poll_seconds, (int, float))
            or poll_seconds < 0
            or poll_seconds > _MAX_POLL_SECONDS
        ):
            raise CanaryError("poll interval must be non-negative")
        journal_file = Path(journal_path)
        token = os.environ.get(CORE_TOKEN_ENV, "").strip()
        if not token:
            raise CanaryError(f"{CORE_TOKEN_ENV} is not configured")
    except CanaryError as exc:
        emit(str(exc))
        return 2

    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }
    requester = request_json
    deadline = monotonic() + float(timeout_seconds)

    def call(method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        if requester is not None:
            return requester(method, path, payload, headers)
        remaining = max(0.1, min(float(timeout_seconds), deadline - monotonic()))
        return _request_json(
            method,
            f"{origin}{path}",
            payload,
            headers,
            timeout_seconds=remaining,
        )

    path = f"/funding/spending-reservations/{quote(reservation_id, safe='')}"
    lock_descriptor: int | None = None
    try:
        lock_descriptor = _acquire_journal_lock(journal_file)
        journal = _load_journal(journal_file)
        if journal is not None and journal.reservation_id != reservation_id:
            raise CanaryError("canary journal belongs to a different reservation")
        row = _reservation_projection(call("GET", path))
        if not isinstance(row, dict):
            raise CanaryError("Core returned an invalid reservation projection")
        idempotency_key = _validate_scope(
            row,
            reservation_id=reservation_id,
            expected_payee=expected_payee,
            expected_amount=expected_amount_atomic,
            expected_executor=expected_executor,
        )
        if journal is not None and journal.idempotency_key != idempotency_key:
            raise CanaryError("canary journal idempotency identity changed")
        if _success_evidence(
            row,
            reservation_id=reservation_id,
            expected_idempotency_key=idempotency_key,
            expected_payee=expected_payee,
            expected_amount=expected_amount_atomic,
            expected_executor=expected_executor,
        ):
            _save_journal(
                journal_file,
                Journal(reservation_id, idempotency_key, "settled"),
            )
            emit("Hosted canary settled with complete Core and watcher evidence")
            return 0
        if journal is None:
            if not submit_once:
                raise CanaryError("no dispatch made; rerun with --submit-once")
            # This marker is the durable single-submit gate.  It is written
            # before entering the only settle POST so a crash cannot cause a
            # restart to submit again.
            journal = Journal(reservation_id, idempotency_key, "dispatching")
            _save_journal(journal_file, journal)
            try:
                call(
                    "POST",
                    f"{path}/settle",
                    {
                        "payment_authorization": {
                            **_exact_business_intent(row),
                        }
                    },
                )
            except (CanaryError, OSError, TimeoutError):
                emit("settle outcome is unknown; reconciling the same reservation")
            else:
                _save_journal(
                    journal_file,
                    Journal(reservation_id, idempotency_key, "settle_dispatched"),
                )
        # A pre-existing journal, a successful dispatch, and an unknown
        # dispatch all enter this same reconcile-only path.
        while True:
            if _success_evidence(
                row,
                reservation_id=reservation_id,
                expected_idempotency_key=idempotency_key,
                expected_payee=expected_payee,
                expected_amount=expected_amount_atomic,
                expected_executor=expected_executor,
            ):
                _save_journal(
                    journal_file,
                    Journal(reservation_id, idempotency_key, "settled"),
                )
                emit("Hosted canary settled with complete Core and watcher evidence")
                return 0
            if monotonic() >= deadline:
                emit("Hosted canary timed out pending reconciliation; no retry was made")
                return 3
            _save_journal(
                journal_file,
                Journal(reservation_id, idempotency_key, "reconciling"),
            )
            try:
                response = _reservation_projection(
                    call("POST", f"{path}/reconcile", {})
                )
                if not isinstance(response, dict):
                    raise CanaryError("Core returned an invalid reconciliation projection")
                row = response
            except (CanaryError, OSError, TimeoutError):
                pass
            if _success_evidence(
                row,
                reservation_id=reservation_id,
                expected_idempotency_key=idempotency_key,
                expected_payee=expected_payee,
                expected_amount=expected_amount_atomic,
                expected_executor=expected_executor,
            ):
                _save_journal(
                    journal_file,
                    Journal(reservation_id, idempotency_key, "settled"),
                )
                emit("Hosted canary settled with complete Core and watcher evidence")
                return 0
            if monotonic() >= deadline:
                emit("Hosted canary timed out pending reconciliation; no retry was made")
                return 3
            if poll_seconds:
                sleep(min(float(poll_seconds), max(0.0, deadline - monotonic())))
            try:
                row = _reservation_projection(call("GET", path))
                if not isinstance(row, dict):
                    raise CanaryError("Core returned an invalid reservation projection")
                observed_idempotency_key = _validate_scope(
                    row,
                    reservation_id=reservation_id,
                    expected_payee=expected_payee,
                    expected_amount=expected_amount_atomic,
                    expected_executor=expected_executor,
                )
                if observed_idempotency_key != idempotency_key:
                    raise CanaryError(
                        "reservation idempotency identity changed during reconciliation"
                    )
            except (CanaryError, OSError, TimeoutError):
                pass
    except (CanaryError, OSError, TimeoutError) as exc:
        emit(str(exc))
        return 2
    finally:
        if lock_descriptor is not None:
            _release_journal_lock(lock_descriptor)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--core-origin", required=True)
    parser.add_argument("--reservation-id", required=True)
    parser.add_argument("--expected-payee", required=True)
    parser.add_argument("--expected-amount-atomic", required=True)
    parser.add_argument("--expected-executor", required=True)
    parser.add_argument("--journal", required=True, type=Path)
    parser.add_argument("--timeout-seconds", type=float, default=120.0)
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    parser.add_argument(
        "--submit-once",
        action="store_true",
        help="permit the one settle POST; omit to inspect/reconcile only",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    return run_canary(
        core_origin=args.core_origin,
        reservation_id=args.reservation_id,
        expected_payee=args.expected_payee,
        expected_amount_atomic=args.expected_amount_atomic,
        expected_executor=args.expected_executor,
        journal_path=args.journal,
        timeout_seconds=args.timeout_seconds,
        poll_seconds=args.poll_seconds,
        submit_once=args.submit_once,
    )


if __name__ == "__main__":
    raise SystemExit(main())
