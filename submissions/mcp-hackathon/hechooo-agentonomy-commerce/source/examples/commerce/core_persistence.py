"""Small, fail-closed persistence primitives for the local Core sandbox.

The production Core services remain responsible for identities, grants,
reservations and audit records.  This module only stores the local composition
metadata, the receipt verification secret, and the deterministic simulated RPC
journal needed to make a process restart observable and safe.
"""

from __future__ import annotations

from datetime import datetime
import fcntl
import json
import os
from pathlib import Path
import re
import secrets
import stat
import tempfile
from typing import Any, Mapping, NoReturn


METADATA_FILENAME = "core-state.json"
RECEIPT_SECRET_FILENAME = "receipt-secret"
SETTLEMENT_JOURNAL_FILENAME = "settlement-rpc.json"
STATE_LOCK_FILENAME = ".core-state.lock"
METADATA_VERSION = 1

_ADDRESS_PATTERN = re.compile(r"^0x[0-9a-fA-F]{40}$")
_HASH_PATTERN = re.compile(r"^0x[0-9a-f]{64}$")
_QUANTITY_PATTERN = re.compile(r"^0x[0-9a-f]+$")
_WORD_PATTERN = re.compile(r"^0x[0-9a-f]{64}$")
_HEX_PATTERN = re.compile(r"^0x[0-9a-f]+$")
_JOURNAL_KEYS = frozenset(
    {"version", "sent_networks", "transactions", "receipts"}
)
_TRANSACTION_KEYS = frozenset({"hash", "from", "nonce", "to", "input"})
_RECEIPT_KEYS = frozenset({"transactionHash", "status", "blockNumber", "logs"})
_LOG_KEYS = frozenset({"address", "topics", "data"})
_METADATA_KEYS = frozenset(
    {
        "version",
        "wallet_address",
        "wallet_identity_id",
        "spending_grant_id",
        "asset_allowance_id",
        "user_id",
        "agent_id",
        "grant_expires_at",
    }
)


class CorePersistenceError(RuntimeError):
    """A local state error that must stop the sandbox rather than self-heal."""


def _atomic_write_bytes(path: Path, data: bytes, *, mode: int = 0o600) -> None:
    """Replace *path* atomically, keeping runtime state private."""

    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=str(path.parent)
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = None
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        os.chmod(path, mode)
        try:
            directory_fd = os.open(path.parent, os.O_RDONLY)
        except OSError:
            directory_fd = None
        if directory_fd is not None:
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    except Exception:
        if descriptor is not None:
            os.close(descriptor)
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        raise


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    _atomic_write_bytes(path, encoded)


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CorePersistenceError(f"persistent Core {label} is unreadable") from exc
    if not isinstance(value, dict):
        raise CorePersistenceError(f"persistent Core {label} must be a JSON object")
    return value


class StateLock:
    """Nonblocking process lock for one persistent Core state directory."""

    def __init__(self, state_dir: Path):
        self.state_dir = Path(state_dir)
        self.path = self.state_dir / STATE_LOCK_FILENAME
        self._descriptor: int | None = None

    def acquire(self) -> None:
        if self._descriptor is not None:
            return
        self.state_dir.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            os.fchmod(descriptor, 0o600)
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            os.close(descriptor)
            raise CorePersistenceError(
                "persistent Core state lock is already owned by another process"
            ) from exc
        except Exception:
            os.close(descriptor)
            raise
        self._descriptor = descriptor

    def release(self) -> None:
        descriptor, self._descriptor = self._descriptor, None
        if descriptor is None:
            return
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)

    def __enter__(self) -> "StateLock":
        self.acquire()
        return self

    def __exit__(self, _exc_type, _exc_value, _traceback) -> None:
        self.release()


class SettlementJournal:
    """Atomic journal of the closed-world simulated settlement RPC."""

    _VERSION = 1

    def __init__(self, path: Path):
        self.path = Path(path)
        self._state = self._load()

    @staticmethod
    def _invalid() -> NoReturn:
        raise CorePersistenceError("persistent Core settlement journal is invalid")

    @classmethod
    def _validate_state(cls, state: dict[str, Any]) -> None:
        if set(state) != _JOURNAL_KEYS:
            cls._invalid()
        version = state.get("version")
        if isinstance(version, bool) or not isinstance(version, int):
            cls._invalid()
        if version != cls._VERSION:
            raise CorePersistenceError(
                "persistent Core settlement journal version is unsupported"
            )

        sent_networks = state.get("sent_networks")
        transactions = state.get("transactions")
        receipts = state.get("receipts")
        if not isinstance(sent_networks, list):
            cls._invalid()
        if not isinstance(transactions, dict) or not isinstance(receipts, dict):
            cls._invalid()
        if len(sent_networks) != len(transactions) or len(transactions) != len(receipts):
            cls._invalid()
        if any(not isinstance(network, str) or not network.strip() for network in sent_networks):
            cls._invalid()
        if set(transactions) != set(receipts):
            cls._invalid()

        for transaction_hash, transaction in transactions.items():
            if not isinstance(transaction_hash, str) or not _HASH_PATTERN.fullmatch(
                transaction_hash
            ):
                cls._invalid()
            if not isinstance(transaction, dict) or set(transaction) != _TRANSACTION_KEYS:
                cls._invalid()
            if transaction.get("hash") != transaction_hash:
                cls._invalid()
            if not isinstance(transaction.get("from"), str) or not _ADDRESS_PATTERN.fullmatch(
                transaction["from"]
            ):
                cls._invalid()
            if not isinstance(transaction.get("to"), str) or not _ADDRESS_PATTERN.fullmatch(
                transaction["to"]
            ):
                cls._invalid()
            nonce = transaction.get("nonce")
            if not isinstance(nonce, str) or not _QUANTITY_PATTERN.fullmatch(nonce):
                cls._invalid()
            input_data = transaction.get("input")
            if (
                not isinstance(input_data, str)
                or not _HEX_PATTERN.fullmatch(input_data)
                or (len(input_data) - 2) % 2 != 0
            ):
                cls._invalid()

            receipt = receipts.get(transaction_hash)
            if not isinstance(receipt, dict) or set(receipt) != _RECEIPT_KEYS:
                cls._invalid()
            if receipt.get("transactionHash") != transaction_hash:
                cls._invalid()
            if receipt.get("status") != "0x1":
                cls._invalid()
            block_number = receipt.get("blockNumber")
            if not isinstance(block_number, str) or not _QUANTITY_PATTERN.fullmatch(
                block_number
            ):
                cls._invalid()
            logs = receipt.get("logs")
            if not isinstance(logs, list) or len(logs) != 1:
                cls._invalid()
            log = logs[0]
            if not isinstance(log, dict) or set(log) != _LOG_KEYS:
                cls._invalid()
            log_address = log.get("address")
            if not isinstance(log_address, str) or not _ADDRESS_PATTERN.fullmatch(
                log_address
            ):
                cls._invalid()
            if log_address.lower() != transaction["to"].lower():
                cls._invalid()
            topics = log.get("topics")
            if (
                not isinstance(topics, list)
                or len(topics) != 3
                or any(
                    not isinstance(topic, str) or not _WORD_PATTERN.fullmatch(topic)
                    for topic in topics
                )
            ):
                cls._invalid()
            data = log.get("data")
            if not isinstance(data, str) or not _WORD_PATTERN.fullmatch(data):
                cls._invalid()

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {
                "version": self._VERSION,
                "sent_networks": [],
                "transactions": {},
                "receipts": {},
            }
        state = _read_json(self.path, label="settlement journal")
        self._validate_state(state)
        return {
            "version": self._VERSION,
            "sent_networks": list(state["sent_networks"]),
            "transactions": dict(state["transactions"]),
            "receipts": dict(state["receipts"]),
        }

    @property
    def sent_networks(self) -> list[str]:
        return list(self._state["sent_networks"])

    @property
    def transactions(self) -> dict[str, dict[str, Any]]:
        return dict(self._state["transactions"])

    @property
    def receipts(self) -> dict[str, dict[str, Any]]:
        return dict(self._state["receipts"])

    def record(
        self,
        network: str,
        transaction_hash: str,
        transaction: Mapping[str, Any],
        receipt: Mapping[str, Any],
    ) -> None:
        """Persist one simulated send before exposing it to the caller."""

        if transaction_hash in self._state["transactions"]:
            return
        next_state = {
            "version": self._VERSION,
            "sent_networks": [*self._state["sent_networks"], network],
            "transactions": {
                **self._state["transactions"],
                transaction_hash: dict(transaction),
            },
            "receipts": {
                **self._state["receipts"],
                transaction_hash: dict(receipt),
            },
        }
        _atomic_write_json(self.path, next_state)
        self._state = next_state


class PersistentCoreState:
    """Metadata, receipt secret and journal owned by one Core sandbox."""

    def __init__(self, state_dir: Path, database_path: Path):
        self.state_dir = Path(state_dir)
        self.database_path = Path(database_path)
        self.metadata_path = self.state_dir / METADATA_FILENAME
        self.receipt_secret_path = self.state_dir / RECEIPT_SECRET_FILENAME
        self.settlement_journal_path = self.state_dir / SETTLEMENT_JOURNAL_FILENAME
        self.metadata: dict[str, Any] | None = None
        self.receipt_secret: str | None = None

    def prepare(self) -> None:
        """Load existing state or create only the first-run receipt secret.

        A database without its metadata (or metadata without its database) is
        treated as an incomplete state and rejected.  This prevents a restart
        from minting a new identity or grant after state loss.
        """

        database_exists = self.database_path.exists()
        metadata_exists = self.metadata_path.exists()
        secret_exists = self.receipt_secret_path.exists()
        if metadata_exists:
            if not database_exists:
                raise CorePersistenceError(
                    "persistent Core metadata exists without its SQLite database"
                )
            self.metadata = self._load_metadata()
            if not secret_exists:
                raise CorePersistenceError(
                    "persistent Core receipt secret is missing"
                )
        elif database_exists:
            raise CorePersistenceError(
                "persistent Core metadata is missing for the existing SQLite database"
            )
        elif secret_exists:
            raise CorePersistenceError(
                "persistent Core receipt secret exists without metadata"
            )
        else:
            self.receipt_secret = secrets.token_urlsafe(48)
            _atomic_write_bytes(
                self.receipt_secret_path,
                self.receipt_secret.encode("ascii"),
            )

        if self.receipt_secret is None:
            try:
                if stat.S_IMODE(self.receipt_secret_path.stat().st_mode) != 0o600:
                    raise CorePersistenceError(
                        "persistent Core receipt secret permissions are too broad"
                    )
                self.receipt_secret = self.receipt_secret_path.read_text(
                    encoding="ascii"
                ).strip()
            except CorePersistenceError:
                raise
            except (OSError, UnicodeError) as exc:
                raise CorePersistenceError(
                    "persistent Core receipt secret is unreadable"
                ) from exc
            if len(self.receipt_secret) < 32:
                raise CorePersistenceError("persistent Core receipt secret is invalid")

    def _load_metadata(self) -> dict[str, Any]:
        metadata = _read_json(self.metadata_path, label="metadata")
        if set(metadata) != _METADATA_KEYS:
            raise CorePersistenceError("persistent Core metadata fields are invalid")
        if metadata.get("version") != METADATA_VERSION:
            raise CorePersistenceError("persistent Core metadata version is unsupported")
        for key in (
            "wallet_identity_id",
            "spending_grant_id",
            "asset_allowance_id",
            "user_id",
            "agent_id",
            "grant_expires_at",
        ):
            if not isinstance(metadata.get(key), str) or not metadata[key].strip():
                raise CorePersistenceError(f"persistent Core metadata field {key} is invalid")
        wallet_address = metadata.get("wallet_address")
        if not isinstance(wallet_address, str) or not _ADDRESS_PATTERN.fullmatch(
            wallet_address
        ):
            raise CorePersistenceError("persistent Core wallet address metadata is invalid")
        try:
            datetime.fromisoformat(metadata["grant_expires_at"])
        except (TypeError, ValueError) as exc:
            raise CorePersistenceError("persistent Core grant expiry metadata is invalid") from exc
        return metadata

    def save_metadata(self, metadata: Mapping[str, Any]) -> None:
        candidate = dict(metadata)
        if set(candidate) != _METADATA_KEYS:
            raise CorePersistenceError("persistent Core metadata fields are invalid")
        candidate["version"] = METADATA_VERSION
        # Reuse the same validation path before replacing the file.
        previous = self.metadata
        self.metadata = self._load_candidate_metadata(candidate)
        try:
            _atomic_write_json(self.metadata_path, self.metadata)
        except Exception:
            self.metadata = previous
            raise

    @staticmethod
    def _load_candidate_metadata(candidate: dict[str, Any]) -> dict[str, Any]:
        if candidate.get("version") != METADATA_VERSION:
            raise CorePersistenceError("persistent Core metadata version is unsupported")
        if set(candidate) != _METADATA_KEYS:
            raise CorePersistenceError("persistent Core metadata fields are invalid")
        for key in (
            "wallet_identity_id",
            "spending_grant_id",
            "asset_allowance_id",
            "user_id",
            "agent_id",
            "grant_expires_at",
        ):
            if not isinstance(candidate.get(key), str) or not candidate[key].strip():
                raise CorePersistenceError(f"persistent Core metadata field {key} is invalid")
        wallet_address = candidate.get("wallet_address")
        if not isinstance(wallet_address, str) or not _ADDRESS_PATTERN.fullmatch(
            wallet_address
        ):
            raise CorePersistenceError("persistent Core wallet address metadata is invalid")
        try:
            datetime.fromisoformat(candidate["grant_expires_at"])
        except (TypeError, ValueError) as exc:
            raise CorePersistenceError("persistent Core grant expiry metadata is invalid") from exc
        return candidate

    def settlement_journal(self) -> SettlementJournal:
        return SettlementJournal(self.settlement_journal_path)
