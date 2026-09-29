"""Read-only recovery of already recorded allowance proofs; never submits gas."""
from __future__ import annotations

import logging
from threading import Event, Thread

from .service import AllowanceAmountMismatch, AllowanceVerificationPending


logger = logging.getLogger(__name__)


class AllowanceReconciler:
    def __init__(self, service, store, *, clock):
        self.service = service
        self.store = store
        self.clock = clock
        self._stop = Event()
        self._thread = None

    def verify(self, record):
        """Keep HTTP and background outcomes identical, with redacted diagnostics."""
        if record.get("status") == "confirmed_mismatch":
            # A terminal mismatch is a durable result, not a new verification
            # request.  Replays must return the same conflict without making
            # another provider call or reopening authority state.
            exc = AllowanceAmountMismatch(
                {
                    "user_id": record["user_id"],
                    "attempt_id": record["attempt_id"],
                    "wallet_identity_id": record["wallet_identity_id"],
                    "network": record["network"],
                    "token_address": record["token_address"],
                    "spender_address": record["spender_address"],
                    "allowance_tx_hash": record["allowance_tx_hash"],
                    "expected_amount_atomic": record["amount_atomic"],
                    "actual_approved_amount_atomic": record[
                        "actual_approved_amount_atomic"
                    ],
                    "observed_allowance_atomic": record[
                        "observed_allowance_atomic"
                    ],
                    "confirmed_block": record["confirmed_block"],
                    "confirmed_block_hash": record["confirmed_block_hash"],
                    "verified_at": record["verified_at"],
                }
            )
            exc.recovery_record = dict(record)
            raise exc
        try:
            allowance = self.service.verify_asset_allowance(expected_amount_atomic=(
                int(record["amount_atomic"]) if record["amount_atomic"] is not None else None
            ), **{
                field: record[field] for field in (
                    "wallet_identity_id", "network", "token_address",
                    "spender_address", "allowance_tx_hash",
                )
            })
        except AllowanceAmountMismatch as exc:
            evidence = dict(exc.evidence)
            evidence.setdefault("attempt_id", record["attempt_id"])
            evidence.setdefault("user_id", record["user_id"])
            recovery_record = self.store.confirm_mismatch(
                attempt_id=record["attempt_id"],
                evidence=evidence,
                now=self.clock(),
            )
            exc.recovery_record = recovery_record
            raise
        except AllowanceVerificationPending:
            self.store.result(attempt_id=record["attempt_id"], status="pending",
                              reason_code="chain_pending", now=self.clock())
            raise
        except ValueError:
            self.store.result(attempt_id=record["attempt_id"], status="attention_required",
                              reason_code="invalid_evidence", now=self.clock())
            raise
        except RuntimeError:
            self.store.result(attempt_id=record["attempt_id"], status="pending",
                              reason_code="rpc_unavailable", now=self.clock())
            raise
        self.store.result(attempt_id=record["attempt_id"], status="verified",
                          reason_code=None, now=self.clock())
        return allowance

    def run_once(self):
        records = self.store.due(now=self.clock(), limit=10)
        for record in records:
            if self._stop.is_set():
                break
            try:
                self.verify(record)
            except (ValueError, RuntimeError):
                # The exact proof is retained; the store owns retry/backoff.
                continue
            except Exception:
                # Lease expiry allows a later read. Do not print provider/DB data.
                logger.warning("Allowance recovery could not finish a recorded proof")
        return len(records)

    def _run(self):
        while not self._stop.is_set():
            try:
                self.run_once()
            except Exception:
                logger.warning("Allowance recovery sweep temporarily unavailable")
            self._stop.wait(15)

    def start(self):
        if self._thread is not None:
            return
        self._thread = Thread(target=self._run, name="allowance-recovery", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1)
