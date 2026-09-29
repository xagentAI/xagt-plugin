"""Independent, fail-closed single-chain Hosted execution watcher.

The watcher owns no signing or broadcast capability.  It reads a separate RPC
client, re-checks the exact transaction and Executor event against the durable
execution scope, and is the only component allowed to advance chain outcome
state.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Mapping

from eth_utils import keccak

from evm import EXECUTE_SELECTOR
from execution_models import ExecutionState
from execution_repository import ExecutionConflict
from shared.hosted_facilitator_protocol import HOSTED_CHAIN_PROFILES


WATCHER_VERSION = "hosted-chain-watcher-v1"
SAFE_BLOCK_TAG = "safe"
MIN_CONFIRMATIONS = 2

_HEX = re.compile(r"^0x[0-9a-fA-F]*$")
_HASH = re.compile(r"^0x[0-9a-fA-F]{64}$")
_ADDRESS = re.compile(r"^0x[0-9a-fA-F]{40}$")
_QUANTITY = re.compile(r"^0x(?:0|[1-9a-fA-F][0-9a-fA-F]*)$")
# Fixed against contracts/src/ClinkBaseUSDCExecutor.sol.  Keep the literal in
# the verifier so an ABI typo cannot silently make the test and decoder agree.
_PAYMENT_EVENT_TOPIC = (
    "0x068133bf9486e7726dcaa3b2b03cb0dd7af09dbbf7f53efcc181881a885059fd"
)
_TRANSFER_EVENT_TOPIC = (
    "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
)
_USED_CAPABILITY_SELECTOR = keccak(text="usedCapabilityHashes(bytes32)")[:4]
_USED_NONCE_SELECTOR = keccak(text="usedNonces(address,uint256)")[:4]


class WatcherConfigurationError(ValueError):
    """The watcher was constructed with an unsafe or incomplete policy."""


class WatcherNotFound(LookupError):
    """The requested execution is not present in the repository."""


@dataclass(frozen=True, slots=True)
class WatchResult:
    execution_id: str
    status: ExecutionState
    action: str
    reason: str
    finality_boundary: str | None = None


@dataclass(frozen=True, slots=True)
class _Observation:
    valid: bool
    reorg: bool = False
    reason: str = "evidence_unavailable"
    receipt_status: int | None = None
    receipt_block_number: int | None = None
    receipt_block_hash: str | None = None
    confirmations: int = 0
    safe_block_number: int | None = None
    safe_block_hash: str | None = None
    accepted_transfer: bool = False
    capability_used: bool = False
    owner_nonce_used: bool = False
    payment_event_found: bool = False
    transfer_event_found: bool = False
    finality_boundary_timestamp: int | None = None
    finality_boundary: str = SAFE_BLOCK_TAG


class _EvidenceError(Exception):
    __slots__ = ("reason", "reorg")

    def __init__(self, reason: str, *, reorg: bool = False) -> None:
        self.reason = reason
        self.reorg = reorg


def _address(value: object, *, field: str) -> str:
    if not isinstance(value, str) or _ADDRESS.fullmatch(value) is None:
        raise _EvidenceError(f"{field}_invalid")
    return value.lower()


def _hash(value: object, *, field: str) -> str:
    if not isinstance(value, str) or _HASH.fullmatch(value) is None:
        raise _EvidenceError(f"{field}_invalid")
    return value.lower()


def _bytes(value: object, *, field: str, allow_empty: bool = True) -> bytes:
    if not isinstance(value, str) or _HEX.fullmatch(value) is None:
        raise _EvidenceError(f"{field}_invalid")
    encoded = value[2:]
    if len(encoded) % 2:
        raise _EvidenceError(f"{field}_invalid")
    try:
        result = bytes.fromhex(encoded)
    except ValueError as exc:
        raise _EvidenceError(f"{field}_invalid") from exc
    if not allow_empty and not result:
        raise _EvidenceError(f"{field}_missing")
    return result


def _quantity(value: object, *, field: str) -> int:
    if not isinstance(value, str) or _QUANTITY.fullmatch(value) is None:
        raise _EvidenceError(f"{field}_invalid")
    try:
        return int(value, 16)
    except ValueError as exc:
        raise _EvidenceError(f"{field}_invalid") from exc


def _word(value: bytes, *, field: str) -> bytes:
    if len(value) != 32:
        raise _EvidenceError(f"{field}_invalid")
    return value


def _word_uint(value: bytes, *, field: str) -> int:
    return int.from_bytes(_word(value, field=field), "big")


def _word_bytes32(value: bytes, *, field: str) -> str:
    return "0x" + _word(value, field=field).hex()


def _word_address(value: bytes, *, field: str) -> str:
    value = _word(value, field=field)
    if value[:12] != bytes(12):
        raise _EvidenceError(f"{field}_invalid")
    return "0x" + value[12:].hex()


def _same_hash(left: object, right: object, *, field: str) -> bool:
    return _hash(left, field=field) == _hash(right, field=field)


def _decode_execute_input(value: object) -> dict[str, Any]:
    raw = _bytes(value, field="transaction_input", allow_empty=False)
    if len(raw) < 4 or raw[:4] != EXECUTE_SELECTOR:
        raise _EvidenceError("transaction_selector_mismatch")
    body = raw[4:]
    # The first argument is ten static words followed by a dynamic bytes
    # argument.  Require the canonical ABI shape, including the 65-byte
    # signature and its zero padding; permissive decoding is unsafe here.
    if len(body) != 480:
        raise _EvidenceError("transaction_input_shape_invalid")
    words = [body[index : index + 32] for index in range(0, 352, 32)]
    if _word_uint(words[10], field="signature_offset") != 352:
        raise _EvidenceError("transaction_input_shape_invalid")
    signature_length = _word_uint(body[352:384], field="signature_length")
    if signature_length != 65:
        raise _EvidenceError("transaction_signature_invalid")
    signature_end = 384 + signature_length
    if any(body[signature_end:480]):
        raise _EvidenceError("transaction_signature_padding_invalid")
    return {
        "capability_hash": _word_bytes32(words[0], field="capability_hash"),
        "reservation_hash": _word_bytes32(words[1], field="reservation_hash"),
        "owner": _word_address(words[2], field="owner"),
        "payee": _word_address(words[3], field="payee"),
        "token": _word_address(words[4], field="token"),
        "amount": _word_uint(words[5], field="amount"),
        "nonce": _word_uint(words[6], field="nonce"),
        "deadline": _word_uint(words[7], field="deadline"),
        "signer_epoch": _word_uint(words[8], field="signer_epoch"),
        "relayer": _word_address(words[9], field="relayer"),
    }


def _decode_payment_event(log: Mapping[str, Any], *, execution: Any) -> bool:
    try:
        if _address(log.get("address"), field="event_address") != _address(
            execution.executor, field="executor"
        ):
            return False
        topics = log.get("topics")
        if not isinstance(topics, list) or len(topics) != 4:
            raise _EvidenceError("payment_event_topics_invalid")
        if not _same_hash(topics[0], _PAYMENT_EVENT_TOPIC, field="event_topic"):
            return False
        if not _same_hash(topics[1], execution.capability_hash, field="capability_hash"):
            raise _EvidenceError("payment_event_scope_mismatch")
        if not _same_hash(topics[2], execution.reservation_hash, field="reservation_hash"):
            raise _EvidenceError("payment_event_scope_mismatch")
        if _word_address(_bytes(topics[3], field="owner_topic", allow_empty=False), field="owner_topic") != _address(
            execution.owner, field="owner"
        ):
            raise _EvidenceError("payment_event_scope_mismatch")
        data = _bytes(log.get("data"), field="payment_event_data")
        # PaymentExecuted's first three fields are indexed.  The remaining
        # eight fields are ABI-encoded in this exact order:
        # payee, token, amount, nonce, deadline, signer, signerEpoch, relayer.
        if len(data) != 256:
            raise _EvidenceError("payment_event_data_invalid")
        payee = _word_address(data[:32], field="event_payee")
        token = _word_address(data[32:64], field="event_token")
        amount = _word_uint(data[64:96], field="event_amount")
        nonce = _word_uint(data[96:128], field="event_nonce")
        deadline = _word_uint(data[128:160], field="event_deadline")
        signer = _word_address(data[160:192], field="event_signer")
        signer_epoch = _word_uint(data[192:224], field="event_signer_epoch")
        relayer = _word_address(data[224:256], field="event_relayer")
        if signer == "0x" + "00" * 20:
            raise _EvidenceError("payment_event_signer_invalid")
        if (
            payee != _address(execution.payee, field="payee")
            or token != _address(execution.token, field="token")
            or amount != int(execution.amount_atomic)
            or nonce != int(execution.owner_nonce)
            or deadline != int(execution.deadline)
            or signer_epoch != int(execution.signer_epoch)
            or relayer != _address(execution.relayer_address, field="relayer_address")
        ):
            raise _EvidenceError("payment_event_scope_mismatch")
        return True
    except AttributeError as exc:
        raise _EvidenceError("payment_event_invalid") from exc


def _decode_transfer_event(log: Mapping[str, Any], *, execution: Any) -> bool:
    """Validate the one canonical USDC transfer emitted by the executor call."""

    try:
        if _address(log.get("address"), field="transfer_event_address") != _address(
            execution.token, field="token"
        ):
            return False
        topics = log.get("topics")
        if not isinstance(topics, list) or len(topics) != 3:
            raise _EvidenceError("transfer_event_topics_invalid")
        if not _same_hash(topics[0], _TRANSFER_EVENT_TOPIC, field="transfer_event_topic"):
            return False
        sender = _word_address(
            _bytes(topics[1], field="transfer_from_topic", allow_empty=False),
            field="transfer_from_topic",
        )
        recipient = _word_address(
            _bytes(topics[2], field="transfer_to_topic", allow_empty=False),
            field="transfer_to_topic",
        )
        data = _bytes(log.get("data"), field="transfer_event_data")
        if len(data) != 32:
            raise _EvidenceError("transfer_event_data_invalid")
        amount = _word_uint(data, field="transfer_event_amount")
        if (
            sender != _address(execution.owner, field="owner")
            or recipient != _address(execution.payee, field="payee")
            or amount != int(execution.amount_atomic)
        ):
            raise _EvidenceError("transfer_event_scope_mismatch")
        return True
    except AttributeError as exc:
        raise _EvidenceError("transfer_event_invalid") from exc


def _abi_address_word(value: object, *, field: str) -> str:
    address = _address(value, field=field)
    return "0" * 24 + address[2:]


class HostedChainWatcher:
    """Reconcile one execution using a separately injected RPC client."""

    def __init__(
        self,
        repository: Any,
        rpc_client: Any,
        *,
        executor_address: str,
        executor_code_hash: str | None = None,
        watcher_version: str = WATCHER_VERSION,
        confirmation_depth: int,
        chain: str,
        token: str,
        finality_boundary: str,
        chain_id: int,
    ) -> None:
        if repository is None:
            raise WatcherConfigurationError("execution repository is required")
        if rpc_client is repository:
            raise WatcherConfigurationError("watcher RPC client must be independent")
        if not callable(getattr(rpc_client, "call", None)) and not callable(rpc_client):
            raise WatcherConfigurationError("independent RPC client is required")
        self._repository = repository
        self._rpc = rpc_client
        try:
            self._executor = _address(executor_address, field="executor_address")
        except _EvidenceError:
            raise WatcherConfigurationError("executor address is invalid") from None
        if self._executor == "0x" + "00" * 20:
            raise WatcherConfigurationError("executor address is invalid")
        if executor_code_hash is not None and (
            not isinstance(executor_code_hash, str)
            or _HASH.fullmatch(executor_code_hash) is None
        ):
            raise WatcherConfigurationError("executor code hash is invalid")
        if not isinstance(watcher_version, str) or not watcher_version or len(watcher_version) > 128:
            raise WatcherConfigurationError("watcher version is invalid")
        if any(ord(char) < 32 or ord(char) == 127 for char in watcher_version):
            raise WatcherConfigurationError("watcher version is invalid")
        profile = HOSTED_CHAIN_PROFILES.get(chain)
        if profile is None:
            raise WatcherConfigurationError("chain profile is not supported")
        if type(chain_id) is not int or chain_id != profile.chain_id:
            raise WatcherConfigurationError("chain ID does not match chain profile")
        if not isinstance(token, str) or token.lower() != profile.token:
            raise WatcherConfigurationError("token does not match chain profile")
        if finality_boundary != profile.finality_boundary:
            raise WatcherConfigurationError("finality boundary does not match chain profile")
        if type(confirmation_depth) is not int or confirmation_depth < profile.min_confirmation_depth:
            raise WatcherConfigurationError("confirmation depth cannot be weakened")
        self._watcher_version = watcher_version
        self._executor_code_hash = (
            executor_code_hash.lower() if executor_code_hash is not None else None
        )
        self._confirmation_depth = confirmation_depth
        self._chain = profile.chain
        self._chain_id = profile.chain_id
        self._token = profile.token
        self._finality_boundary = finality_boundary

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(chain={self._chain!r}, executor={self._executor!r}, "
            f"confirmation_depth={self._confirmation_depth!r}, version={self._watcher_version!r})"
        )

    @property
    def chain(self) -> str:
        return self._chain

    @property
    def chain_id(self) -> int:
        return self._chain_id

    @property
    def token(self) -> str:
        return self._token

    @property
    def finality_boundary(self) -> str:
        return self._finality_boundary

    @property
    def confirmation_depth(self) -> int:
        return self._confirmation_depth

    def watch(self, execution_id: str) -> WatchResult:
        execution = self._repository.get_execution(execution_id)
        if execution is None:
            raise WatcherNotFound("execution not found")
        status = ExecutionState(execution.status)
        if status is ExecutionState.FINALIZED:
            return self._watch_finalized(execution)
        if status is ExecutionState.REVERTED:
            return self._watch_reverted(execution)
        if status in {
            ExecutionState.PREFLIGHT_APPROVED,
            ExecutionState.SIGNING,
        }:
            try:
                released = self._repository.release_expired(execution_id)
            except ExecutionConflict:
                return WatchResult(
                    execution_id,
                    status,
                    "unchanged",
                    "authorization_active",
                )
            return WatchResult(
                execution_id,
                ExecutionState(released.status),
                "released",
                "deadline_expired",
            )
        if status not in {
            ExecutionState.SUBMITTED,
            ExecutionState.SUBMISSION_UNKNOWN,
            ExecutionState.SUBMISSION_REJECTED,
            ExecutionState.CONFIRMED,
        }:
            return WatchResult(execution_id, status, "unchanged", "state_not_watchable")

        observation = self._observe(execution)
        if not observation.valid:
            return WatchResult(execution_id, status, "unchanged", observation.reason)

        try:
            if observation.receipt_status == 1:
                confirmed = self._repository.confirm(
                    execution_id,
                    receipt_status=1,
                    receipt_block_number=observation.receipt_block_number,
                    receipt_block_hash=observation.receipt_block_hash,
                    confirmations=observation.confirmations,
                    safe_block_number=observation.safe_block_number,
                    safe_block_hash=observation.safe_block_hash,
                    watcher_version=self._watcher_version,
                    finality_boundary=self._finality_boundary,
                    evidence=self._evidence(observation),
                )
                if ExecutionState(confirmed.status) is ExecutionState.CONFIRMED:
                    try:
                        finalized = self._repository.finalize(
                            execution_id,
                            finality_boundary=self._finality_boundary,
                        )
                    except Exception:
                        return WatchResult(
                            execution_id,
                            ExecutionState.CONFIRMED,
                            "confirmed",
                            f"{self._finality_boundary}_evidence_verified",
                            self._finality_boundary,
                        )
                    return WatchResult(
                        execution_id,
                        ExecutionState(finalized.status),
                        "finalized",
                        f"{self._finality_boundary}_evidence_verified",
                        self._finality_boundary,
                    )
                return WatchResult(
                    execution_id,
                    ExecutionState(confirmed.status),
                    "confirmed",
                    f"{self._finality_boundary}_evidence_verified",
                    self._finality_boundary,
                )
            reverted = self._repository.revert(
                execution_id,
                receipt_status=0,
                receipt_block_number=observation.receipt_block_number,
                receipt_block_hash=observation.receipt_block_hash,
                confirmations=observation.confirmations,
                safe_block_number=observation.safe_block_number,
                safe_block_hash=observation.safe_block_hash,
                accepted_transfer=False,
                watcher_version=self._watcher_version,
                finality_boundary=self._finality_boundary,
                evidence=self._evidence(observation),
            )
            return WatchResult(
                execution_id,
                ExecutionState(reverted.status),
                "reverted",
                f"{self._finality_boundary}_revert_evidence_verified",
                self._finality_boundary,
            )
        except Exception:
            # A concurrent state change or repository constraint must never be
            # converted into a new economic action or a success claim.
            return WatchResult(execution_id, status, "unchanged", "repository_rejected")

    def _watch_reverted(self, execution: Any) -> WatchResult:
        """Re-observe a failed receipt until its signed replay window closes."""

        observation = self._observe(execution)
        if not observation.valid:
            return WatchResult(
                execution.execution_id,
                ExecutionState.REVERTED,
                "unchanged",
                observation.reason,
                self._finality_boundary,
            )
        if observation.receipt_status != 0:
            return WatchResult(
                execution.execution_id,
                ExecutionState.REVERTED,
                "unchanged",
                "receipt_status_changed",
                self._finality_boundary,
            )
        boundary_timestamp = observation.finality_boundary_timestamp
        if boundary_timestamp is None or boundary_timestamp < int(execution.deadline):
            return WatchResult(
                execution.execution_id,
                ExecutionState.REVERTED,
                "unchanged",
                "authorization_replay_window",
                self._finality_boundary,
            )
        try:
            released = self._repository.release_reverted(
                execution.execution_id,
                receipt_status=0,
                receipt_block_number=observation.receipt_block_number,
                receipt_block_hash=observation.receipt_block_hash,
                confirmations=observation.confirmations,
                safe_block_number=observation.safe_block_number,
                safe_block_hash=observation.safe_block_hash,
                watcher_version=self._watcher_version,
                finality_boundary=self._finality_boundary,
                release_evidence=self._release_evidence(observation),
            )
        except Exception:
            return WatchResult(
                execution.execution_id,
                ExecutionState.REVERTED,
                "unchanged",
                "repository_rejected",
                self._finality_boundary,
            )
        return WatchResult(
            execution.execution_id,
            ExecutionState(released.status),
            "released",
            "safe_revert_release",
            self._finality_boundary,
        )

    def _watch_finalized(self, execution: Any) -> WatchResult:
        observation = self._observe(execution, detect_reorg=True)
        if observation.reorg:
            try:
                reviewed = self._repository.mark_reorg_review(
                    execution.execution_id,
                    evidence={
                        "canonical": False,
                        "observed_block_hash": observation.receipt_block_hash or "unknown",
                        "previous_block_hash": execution.receipt_block_hash or "unknown",
                        "reason": observation.reason,
                        "watcher_version": self._watcher_version,
                    },
                )
                return WatchResult(
                    execution.execution_id,
                    ExecutionState(reviewed.status),
                    "reorg_review",
                    observation.reason,
                    self._finality_boundary,
                )
            except Exception:
                return WatchResult(
                    execution.execution_id,
                    ExecutionState.FINALIZED,
                    "unchanged",
                    "repository_rejected",
                    self._finality_boundary,
                )
        if observation.valid:
            return WatchResult(
                execution.execution_id,
                ExecutionState.FINALIZED,
                "unchanged",
                "canonical_evidence_verified",
                self._finality_boundary,
            )
        return WatchResult(
            execution.execution_id,
            ExecutionState.FINALIZED,
            "unchanged",
            observation.reason,
            self._finality_boundary,
        )

    def _rpc_call(self, method: str, params: list[Any]) -> Any:
        try:
            call = getattr(self._rpc, "call", None)
            if callable(call):
                return call(method, params)
            return self._rpc(method, params)
        except Exception as exc:
            raise _EvidenceError("rpc_unavailable") from exc

    def _observe(self, execution: Any, *, detect_reorg: bool = False) -> _Observation:
        try:
            if execution.raw_transaction_hash is None:
                raise _EvidenceError("transaction_hash_missing")
            if execution.chain != self._chain:
                raise _EvidenceError("chain_scope_mismatch")
            stored_boundary = getattr(execution, "finality_boundary", None)
            if stored_boundary is not None and stored_boundary != self._finality_boundary:
                raise _EvidenceError("finality_boundary_mismatch")
            if _address(execution.token, field="token") != self._token:
                raise _EvidenceError("token_scope_mismatch")
            tx_hash = _hash(execution.raw_transaction_hash, field="transaction_hash")
            if _address(execution.executor, field="executor") != self._executor:
                raise _EvidenceError("executor_scope_mismatch")
            relayer_address = _address(execution.relayer_address, field="relayer_address")
            chain_id = _quantity(self._rpc_call("eth_chainId", []), field="chain_id")
            if chain_id != self._chain_id:
                raise _EvidenceError("chain_id_mismatch")
            transaction = self._rpc_call("eth_getTransactionByHash", [tx_hash])
            receipt = self._rpc_call("eth_getTransactionReceipt", [tx_hash])
            if not isinstance(transaction, Mapping) or not isinstance(receipt, Mapping):
                raise _EvidenceError("evidence_unavailable")
            if _hash(transaction.get("hash"), field="transaction_hash") != tx_hash:
                raise _EvidenceError("transaction_hash_mismatch")
            if _hash(receipt.get("transactionHash"), field="receipt_transaction_hash") != tx_hash:
                raise _EvidenceError("receipt_transaction_hash_mismatch")
            tx_to = _address(transaction.get("to"), field="transaction_to")
            if tx_to != self._executor:
                raise _EvidenceError("transaction_destination_mismatch")
            if _address(transaction.get("from"), field="transaction_from") != relayer_address:
                raise _EvidenceError("transaction_sender_mismatch")
            tx_nonce = _quantity(transaction.get("nonce"), field="transaction_nonce")
            if tx_nonce != int(execution.relayer_nonce):
                raise _EvidenceError("transaction_nonce_mismatch")
            if _quantity(transaction.get("value"), field="transaction_value") != 0:
                raise _EvidenceError("transaction_value_mismatch")
            if _quantity(transaction.get("type"), field="transaction_type") != 2:
                raise _EvidenceError("transaction_type_mismatch")
            tx_chain_id = _quantity(transaction.get("chainId"), field="transaction_chain_id")
            if tx_chain_id != self._chain_id:
                raise _EvidenceError("transaction_chain_id_mismatch")
            decoded = _decode_execute_input(transaction.get("input"))
            self._match_execution(decoded, execution)

            receipt_block_number = _quantity(receipt.get("blockNumber"), field="receipt_block_number")
            receipt_block_hash = _hash(receipt.get("blockHash"), field="receipt_block_hash")
            receipt_status = _quantity(receipt.get("status"), field="receipt_status")
            if receipt_status not in {0, 1}:
                raise _EvidenceError("receipt_status_invalid")
            tx_block_number = _quantity(transaction.get("blockNumber"), field="transaction_block_number")
            tx_block_hash = _hash(transaction.get("blockHash"), field="transaction_block_hash")
            if tx_block_number != receipt_block_number or tx_block_hash != receipt_block_hash:
                raise _EvidenceError(
                    "canonical_block_changed" if detect_reorg else "block_evidence_mismatch",
                    reorg=detect_reorg,
                )
            receipt_block = self._rpc_call(
                "eth_getBlockByNumber", [hex(receipt_block_number), False]
            )
            safe_block = self._rpc_call("eth_getBlockByNumber", [self._finality_boundary, False])
            try:
                self._check_block(
                    receipt_block,
                    receipt_block_number,
                    receipt_block_hash,
                    field="receipt_block",
                )
            except _EvidenceError as exc:
                if detect_reorg and exc.reason == "canonical_block_mismatch":
                    raise _EvidenceError("canonical_block_changed", reorg=True) from exc
                raise
            if not isinstance(safe_block, Mapping):
                raise _EvidenceError("safe_block_unavailable")
            safe_block_number = _quantity(safe_block.get("number"), field="safe_block_number")
            safe_block_hash = _hash(safe_block.get("hash"), field="safe_block_hash")
            finality_boundary_timestamp = _quantity(
                safe_block.get("timestamp"), field="finality_boundary_timestamp"
            )
            boundary_block = hex(safe_block_number)
            confirmations = safe_block_number - receipt_block_number
            if safe_block_number < receipt_block_number or confirmations < self._confirmation_depth:
                raise _EvidenceError("confirmation_depth_insufficient")
            if detect_reorg:
                if receipt_status != 1:
                    raise _EvidenceError("receipt_status_changed", reorg=True)
                previous_block_hash = execution.receipt_block_hash
                if previous_block_hash is not None and receipt_block_hash != _hash(
                    previous_block_hash, field="stored_receipt_block_hash"
                ):
                    raise _EvidenceError("canonical_block_changed", reorg=True)
            for address, field in ((self._executor, "executor_code"), (self._token, "token_code")):
                code = _bytes(
                    self._rpc_call("eth_getCode", [address, boundary_block]),
                    field=field,
                )
                if not code:
                    raise _EvidenceError(f"{field}_missing")
                if (
                    field == "executor_code"
                    and self._executor_code_hash is not None
                    and "0x" + keccak(code).hex() != self._executor_code_hash
                ):
                    raise _EvidenceError("executor_code_mismatch")
            call_data = "0x" + _USED_CAPABILITY_SELECTOR.hex() + tx_hash_from_hash(
                execution.capability_hash
            )
            used = self._decode_bool(
                self._rpc_call(
                    "eth_call",
                    [{"to": self._executor, "data": call_data}, boundary_block],
                ),
                field="used_capability",
            )
            owner_nonce_data = (
                "0x"
                + _USED_NONCE_SELECTOR.hex()
                + _abi_address_word(execution.owner, field="owner")
                + f"{int(execution.owner_nonce):064x}"
            )
            owner_nonce_used = self._decode_bool(
                self._rpc_call(
                    "eth_call",
                    [
                        {"to": self._executor, "data": owner_nonce_data},
                        boundary_block,
                    ],
                ),
                field="used_owner_nonce",
            )
            payment_events = receipt.get("logs")
            if not isinstance(payment_events, list):
                raise _EvidenceError("receipt_logs_invalid")
            matching_payment_events = []
            matching_transfer_events = []
            for log in payment_events:
                if not isinstance(log, Mapping):
                    raise _EvidenceError("receipt_log_invalid")
                topics = log.get("topics")
                if not isinstance(topics, list) or not topics:
                    continue
                topic = topics[0]
                if not isinstance(topic, str):
                    continue
                topic = topic.lower()
                if topic == _PAYMENT_EVENT_TOPIC:
                    try:
                        address = _address(log.get("address"), field="event_address")
                    except _EvidenceError:
                        continue
                    if address == self._executor:
                        matching_payment_events.append(log)
                elif topic == _TRANSFER_EVENT_TOPIC:
                    try:
                        address = _address(log.get("address"), field="transfer_event_address")
                    except _EvidenceError:
                        continue
                    if address == self._token:
                        matching_transfer_events.append(log)
            if len(matching_payment_events) > 1:
                raise _EvidenceError("payment_event_ambiguous")
            if len(matching_transfer_events) > 1:
                raise _EvidenceError("transfer_event_ambiguous")
            payment_event_found = False
            if matching_payment_events:
                payment_event_found = _decode_payment_event(
                    matching_payment_events[0], execution=execution
                )
                if not payment_event_found:
                    raise _EvidenceError("payment_event_invalid")
            transfer_event_found = False
            if matching_transfer_events:
                transfer_event_found = _decode_transfer_event(
                    matching_transfer_events[0], execution=execution
                )
                if not transfer_event_found:
                    raise _EvidenceError("transfer_event_invalid")
            if receipt_status == 1:
                if (
                    not payment_event_found
                    or not transfer_event_found
                    or not used
                    or not owner_nonce_used
                ):
                    raise _EvidenceError("accepted_transfer_unverified")
            elif (
                payment_event_found
                or transfer_event_found
                or used
                or owner_nonce_used
            ):
                raise _EvidenceError("failed_receipt_transfer_ambiguous")
            return _Observation(
                valid=True,
                receipt_status=receipt_status,
                receipt_block_number=receipt_block_number,
                receipt_block_hash=receipt_block_hash,
                confirmations=confirmations,
                safe_block_number=safe_block_number,
                safe_block_hash=safe_block_hash,
                accepted_transfer=transfer_event_found,
                capability_used=used,
                owner_nonce_used=owner_nonce_used,
                payment_event_found=payment_event_found,
                transfer_event_found=transfer_event_found,
                finality_boundary_timestamp=finality_boundary_timestamp,
                finality_boundary=self._finality_boundary,
            )
        except _EvidenceError as exc:
            return _Observation(valid=False, reorg=exc.reorg, reason=exc.reason)
        except Exception:
            return _Observation(valid=False, reason="evidence_unavailable")

    @staticmethod
    def _check_block(
        block: object,
        expected_number: int,
        expected_hash: str,
        *,
        field: str,
    ) -> None:
        if not isinstance(block, Mapping):
            raise _EvidenceError(f"{field}_unavailable")
        number = _quantity(block.get("number"), field=f"{field}_number")
        block_hash = _hash(block.get("hash"), field=f"{field}_hash")
        if number != expected_number or block_hash != expected_hash:
            raise _EvidenceError("canonical_block_mismatch")

    @staticmethod
    def _match_execution(decoded: Mapping[str, Any], execution: Any) -> None:
        expected = {
            "capability_hash": _hash(execution.capability_hash, field="capability_hash"),
            "reservation_hash": _hash(execution.reservation_hash, field="reservation_hash"),
            "owner": _address(execution.owner, field="owner"),
            "payee": _address(execution.payee, field="payee"),
            "token": _address(execution.token, field="token"),
            "amount": int(execution.amount_atomic),
            "nonce": int(execution.owner_nonce),
            "deadline": int(execution.deadline),
            "signer_epoch": int(execution.signer_epoch),
            "relayer": _address(execution.relayer_address, field="relayer_address"),
        }
        for field, expected_value in expected.items():
            actual = decoded.get(field)
            if isinstance(expected_value, str) and isinstance(actual, str):
                if actual.lower() != expected_value.lower():
                    raise _EvidenceError("transaction_scope_mismatch")
            elif actual != expected_value:
                raise _EvidenceError("transaction_scope_mismatch")

    @staticmethod
    def _decode_bool(value: object, *, field: str) -> bool:
        raw = _bytes(value, field=field)
        if len(raw) != 32:
            raise _EvidenceError(f"{field}_invalid")
        integer = int.from_bytes(raw, "big")
        if integer not in {0, 1}:
            raise _EvidenceError(f"{field}_invalid")
        return bool(integer)

    def _evidence(self, observation: _Observation) -> dict[str, object]:
        return {
            "accepted_transfer": observation.accepted_transfer,
            "boundary": self._finality_boundary,
            "finality_boundary": self._finality_boundary,
            "confirmations": observation.confirmations,
            "receipt_block_number": observation.receipt_block_number,
            "safe_block_number": observation.safe_block_number,
            "watcher_version": self._watcher_version,
            "capability_used": observation.capability_used,
            "owner_nonce_used": observation.owner_nonce_used,
            "payment_event_found": observation.payment_event_found,
            "transfer_event_found": observation.transfer_event_found,
            "finality_boundary_timestamp": observation.finality_boundary_timestamp,
        }

    @staticmethod
    def _release_evidence(observation: _Observation) -> dict[str, object]:
        return {
            "receipt_status": 0,
            "canonical_receipt": True,
            "finality_boundary_timestamp": observation.finality_boundary_timestamp,
            "capability_used": False,
            "owner_nonce_used": False,
            "payment_event_found": False,
            "transfer_event_found": False,
        }


def tx_hash_from_hash(value: object) -> str:
    """Return a validated bytes32 without exposing any transport material."""

    return _hash(value, field="capability_hash")[2:]


ChainWatcher = HostedChainWatcher
