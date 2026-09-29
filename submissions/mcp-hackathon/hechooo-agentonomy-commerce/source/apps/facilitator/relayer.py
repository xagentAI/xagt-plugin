"""One-action Hosted USDC relayer orchestration for one chain profile."""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any, Protocol

from evm import (
    EIP1559Transaction,
    ExecutionAuthorization,
    encode_eip1559_signed,
    encode_eip1559_unsigned,
    encode_execute_calldata,
    eip1559_signing_hash,
    hash_execution,
)
from execution_models import (
    BASE_CHAIN_ID,
    BASE_SEPOLIA_CHAIN_ID,
    ExecutionIntent,
    ExecutionState,
    HostedExecution,
)
from execution_repository import ExecutionConflict, ExecutionRepository
from pilot_gate import PilotGateDenied, worst_case_gas_usd_micros
from rpc import RpcSubmissionRejected, RpcSubmissionUnknown
from shared.hosted_facilitator_protocol import HOSTED_CHAIN_PROFILES


_HEX_QUANTITY = re.compile(r"^0x(?:0|[1-9a-f][0-9a-f]*)$")
_HEX_UINT256_WORD = re.compile(r"^0x[0-9a-f]{64}$")
_TX_HASH = re.compile(r"^0x[0-9a-f]{64}$")
_BASE_GAS_PRICE_ORACLE = "0x420000000000000000000000000000000000000f"
_BASE_L1_BLOCK = "0x4200000000000000000000000000000000000015"
_GET_L1_FEE_UPPER_BOUND_SELECTOR = bytes.fromhex("f1c7a58b")
_OPERATOR_FEE_SCALAR_SELECTOR = "0x4d5d9a2a"
_OPERATOR_FEE_CONSTANT_SELECTOR = "0x16d3bc7f"
_OPERATOR_FEE_DECIMALS = 1_000_000


class DigestSigner(Protocol):
    @property
    def key_id(self) -> str: ...

    @property
    def expected_signer_address(self) -> str: ...

    def sign_digest(self, digest: bytes) -> bytes: ...


class RpcClient(Protocol):
    def call(self, method: str, params: list[Any]) -> Any: ...


class ExecutionApprovalVerifier(Protocol):
    def verify(self, intent: ExecutionIntent) -> None: ...


class RelayerExecutionError(RuntimeError):
    """A bounded, secret-free Hosted relayer failure."""


def _address(value: object, *, field: str) -> str:
    if not isinstance(value, str) or len(value) != 42 or not value.startswith("0x"):
        raise ValueError(f"{field} is invalid")
    try:
        raw = bytes.fromhex(value[2:])
    except ValueError:
        raise ValueError(f"{field} is invalid") from None
    if len(raw) != 20 or raw == bytes(20):
        raise ValueError(f"{field} is invalid")
    return "0x" + raw.hex()


def _quantity(value: object, *, field: str) -> int:
    if not isinstance(value, str) or _HEX_QUANTITY.fullmatch(value) is None:
        raise RelayerExecutionError(f"{field} is invalid")
    return int(value, 16)


def _uint256_word(value: object, *, field: str) -> int:
    if not isinstance(value, str) or _HEX_UINT256_WORD.fullmatch(value) is None:
        raise RelayerExecutionError(f"{field} is invalid")
    return int(value, 16)


class HostedSubmissionReconciler:
    """Inspect or explicitly rebroadcast one persisted Hosted transaction."""

    _SUBMISSION_STATES = frozenset(
        {
            ExecutionState.SIGNED,
            ExecutionState.SUBMITTED,
            ExecutionState.SUBMISSION_UNKNOWN,
            ExecutionState.SUBMISSION_REJECTED,
        }
    )

    def __init__(
        self,
        *,
        repository: ExecutionRepository,
        rpc: RpcClient,
        inspection_rpc: RpcClient | None = None,
        executor_address: str,
        relayer_address: str,
        clock: Callable[[], int],
        chain: str,
        token: str,
        chain_id: int,
    ) -> None:
        if not isinstance(repository, ExecutionRepository):
            raise TypeError("execution repository is required")
        if not callable(getattr(rpc, "call", None)):
            raise TypeError("RPC client is required")
        if inspection_rpc is not None and not callable(
            getattr(inspection_rpc, "call", None)
        ):
            raise TypeError("inspection RPC client is required")
        profile = HOSTED_CHAIN_PROFILES.get(chain)
        if profile is None or profile.chain_id != chain_id:
            raise ValueError("relayer chain profile is invalid")
        if not isinstance(token, str) or token.lower() != profile.token:
            raise ValueError("relayer token does not match chain profile")
        if not callable(clock):
            raise TypeError("relayer clock is required")
        self._repository = repository
        self._rpc = rpc
        self._inspection_rpc = rpc if inspection_rpc is None else inspection_rpc
        self._chain = profile.chain
        self._chain_id = profile.chain_id
        self._token = profile.token
        self._executor_address = _address(executor_address, field="executor address")
        self._relayer_address = _address(relayer_address, field="relayer address")
        if self._executor_address == self._relayer_address:
            raise ValueError("executor and relayer addresses must differ")
        self._clock = clock

    def inspect_submission(self, execution_id: str) -> HostedExecution:
        execution, _found = self.inspect_submission_with_evidence(execution_id)
        return execution

    def inspect_submission_with_evidence(
        self, execution_id: str
    ) -> tuple[HostedExecution, bool]:
        """Return persisted state and whether the exact transaction was found."""

        return self._inspect_submission(execution_id)

    def rebroadcast_identical(self, execution_id: str) -> HostedExecution:
        execution, found = self._inspect_submission(execution_id)
        if found or execution.status not in self._SUBMISSION_STATES:
            return execution

        self._require_submission_rpc_chain()
        now = self._now()
        if execution.status is ExecutionState.SIGNED:
            try:
                claimed, acquired = self._repository.claim_submission(
                    execution_id,
                    now=now,
                )
            except ExecutionConflict:
                latest = self._repository.get_execution(execution_id)
                if latest is None:
                    raise RelayerExecutionError("persisted execution is unavailable")
                if latest.status is ExecutionState.SUBMITTED:
                    return latest
                raise
            if acquired:
                expected = claimed
                raw = self._require_raw_transaction(expected)
            else:
                latest, _found = self._inspect_submission(execution_id)
                return latest
        else:
            raw = self._repository.rebroadcast_raw_transaction(
                execution_id,
                now=now,
            )
            expected = self._repository.mark_submission_unknown(
                execution_id,
                now=now,
            )
        expected_raw = self._require_raw_transaction(expected)
        if raw != expected_raw or expected.raw_transaction_hash is None:
            raise RelayerExecutionError("persisted transaction is unavailable")
        try:
            returned_hash = self._rpc.call(
                "eth_sendRawTransaction", ["0x" + raw.hex()]
            )
        except RpcSubmissionUnknown:
            return self._repository.mark_submission_unknown(
                execution_id,
                now=now,
            )
        except RpcSubmissionRejected as exc:
            return self._repository.mark_submission_rejected(
                execution_id,
                reason_code=exc.reason_code,
                now=now,
            )
        except Exception:
            return expected
        if returned_hash != expected.raw_transaction_hash:
            self._repository.mark_submission_unknown(execution_id, now=now)
            raise RelayerExecutionError("RPC returned a conflicting transaction hash")
        return self._repository.mark_submitted(execution_id, now=now)

    def _inspect_submission(
        self, execution_id: str
    ) -> tuple[HostedExecution, bool]:
        execution = self._repository.get_execution(execution_id)
        if execution is None:
            raise RelayerExecutionError("persisted execution is unavailable")
        self._require_bound_execution(execution)
        if execution.status not in self._SUBMISSION_STATES:
            return execution, False
        self._require_rpc_chain()
        found = self._lookup_exact_transaction(execution)
        if not found:
            return execution, False
        if execution.status in {
            ExecutionState.SIGNED,
            ExecutionState.SUBMISSION_UNKNOWN,
            ExecutionState.SUBMISSION_REJECTED,
        }:
            return self._repository.mark_submitted(
                execution_id,
                now=self._now(),
            ), True
        return execution, True

    def _lookup_exact_transaction(self, execution: HostedExecution) -> bool:
        tx_hash = execution.raw_transaction_hash
        if tx_hash is None or _TX_HASH.fullmatch(tx_hash) is None:
            raise RelayerExecutionError("persisted transaction hash is unavailable")
        result = self._rpc_read("eth_getTransactionByHash", [tx_hash])
        if result is None:
            return False
        if not isinstance(result, dict) or result.get("hash") != tx_hash:
            raise RelayerExecutionError("RPC transaction lookup is inconsistent")
        expected_input = "0x" + encode_execute_calldata(
            self._authorization(execution),
            execution.signature,
        ).hex()
        expected = {
            "from": self._relayer_address,
            "to": self._executor_address,
            "nonce": hex(execution.relayer_nonce),
            "value": "0x0",
            "type": "0x2",
            "chainId": hex(self._chain_id),
            "input": expected_input,
        }
        for field, value in expected.items():
            actual = result.get(field)
            if field in {"from", "to", "input"} and isinstance(actual, str):
                matches = actual.lower() == value.lower()
            else:
                matches = actual == value
            if not matches:
                raise RelayerExecutionError("RPC transaction lookup is inconsistent")
        return True

    def _require_bound_execution(self, execution: HostedExecution) -> None:
        if (
            execution.chain != self._chain
            or execution.token != self._token
            or execution.executor != self._executor_address
            or execution.relayer_address != self._relayer_address
        ):
            raise RelayerExecutionError(
                "execution chain or token does not match operator configuration"
            )

    def _authorization(self, execution: ExecutionIntent) -> ExecutionAuthorization:
        return ExecutionAuthorization(
            capability_hash=execution.capability_hash,
            reservation_hash=execution.reservation_hash,
            owner=execution.owner,
            payee=execution.payee,
            token=execution.token,
            amount=int(execution.amount_atomic),
            nonce=execution.owner_nonce,
            deadline=execution.deadline,
            signer_epoch=execution.signer_epoch,
            relayer=execution.relayer_address,
            chain_id=self._chain_id,
        )

    def _require_rpc_chain(self) -> None:
        chain_id = _quantity(
            self._rpc_read("eth_chainId", []),
            field="RPC chain ID",
        )
        if chain_id != self._chain_id:
            raise RelayerExecutionError("RPC chain does not match operator configuration")

    def _rpc_read(self, method: str, params: list[Any]) -> Any:
        try:
            return self._inspection_rpc.call(method, params)
        except RelayerExecutionError:
            raise
        except Exception:
            raise RelayerExecutionError("RPC dependency is unavailable") from None

    def _require_submission_rpc_chain(self) -> None:
        try:
            result = self._rpc.call("eth_chainId", [])
        except Exception:
            raise RelayerExecutionError(
                "submission RPC dependency is unavailable"
            ) from None
        chain_id = _quantity(result, field="submission RPC chain ID")
        if chain_id != self._chain_id:
            raise RelayerExecutionError(
                "submission RPC chain does not match operator configuration"
            )

    def _now(self) -> int:
        value = self._clock()
        if type(value) is not int or value <= 0:
            raise RelayerExecutionError("relayer clock is unavailable")
        return value

    @staticmethod
    def _require_raw_transaction(execution: HostedExecution) -> bytes:
        if (
            not isinstance(execution.raw_transaction, bytes)
            or not execution.raw_transaction
            or execution.raw_transaction_hash is None
        ):
            raise RelayerExecutionError("persisted transaction is unavailable")
        return execution.raw_transaction


class HostedRelayer:
    """Build, persist and submit one immutable Executor transaction.

    Automatic retries are intentionally absent. A caller may inspect an
    ambiguous transaction or explicitly rebroadcast the exact stored bytes.
    """

    def __init__(
        self,
        *,
        repository: ExecutionRepository,
        rpc: RpcClient,
        inspection_rpc: RpcClient | None = None,
        execution_signer: DigestSigner,
        gas_signer: DigestSigner,
        approval_verifier: ExecutionApprovalVerifier,
        executor_address: str,
        relayer_address: str,
        max_gas_limit: int,
        max_fee_per_gas_wei: int,
        max_priority_fee_per_gas_wei: int,
        max_total_fee_wei: int | None = None,
        clock: Callable[[], int],
        chain: str,
        token: str,
        chain_id: int,
    ) -> None:
        if not isinstance(repository, ExecutionRepository):
            raise TypeError("execution repository is required")
        if not callable(getattr(rpc, "call", None)):
            raise TypeError("RPC client is required")
        if inspection_rpc is not None and not callable(
            getattr(inspection_rpc, "call", None)
        ):
            raise TypeError("inspection RPC client is required")
        if not callable(getattr(execution_signer, "sign_digest", None)):
            raise TypeError("execution signer is required")
        if not callable(getattr(gas_signer, "sign_digest", None)):
            raise TypeError("gas signer is required")
        if not callable(getattr(approval_verifier, "verify", None)):
            raise TypeError("Core execution approval verifier is required")
        self._repository = repository
        self._rpc = rpc
        self._execution_signer = execution_signer
        self._gas_signer = gas_signer
        self._approval_verifier = approval_verifier
        profile = HOSTED_CHAIN_PROFILES.get(chain)
        if profile is None or profile.chain_id != chain_id:
            raise ValueError("relayer chain profile is invalid")
        if not isinstance(token, str) or token.lower() != profile.token:
            raise ValueError("relayer token does not match chain profile")
        self._chain = profile.chain
        self._chain_id = profile.chain_id
        self._token = profile.token
        self._executor_address = _address(executor_address, field="executor address")
        self._relayer_address = _address(relayer_address, field="relayer address")
        if self._executor_address == self._relayer_address:
            raise ValueError("executor and relayer addresses must differ")
        execution_key_id = getattr(execution_signer, "key_id", None)
        gas_key_id = getattr(gas_signer, "key_id", None)
        if (
            not isinstance(execution_key_id, str)
            or not execution_key_id
            or not isinstance(gas_key_id, str)
            or not gas_key_id
        ):
            raise ValueError("signer key identities are required")
        if execution_key_id == gas_key_id:
            raise ValueError("execution and gas signer keys must differ")
        execution_address = _address(
            getattr(execution_signer, "expected_signer_address", None),
            field="execution signer address",
        )
        gas_address = _address(
            getattr(gas_signer, "expected_signer_address", None),
            field="gas signer address",
        )
        if execution_address == gas_address:
            raise ValueError("execution and gas signer addresses must differ")
        if gas_address != self._relayer_address:
            raise ValueError("gas signer does not match relayer address")
        self._execution_signer_address = execution_address
        self._max_gas_limit = self._positive_limit(max_gas_limit, "gas limit")
        self._max_fee_per_gas_wei = self._positive_limit(
            max_fee_per_gas_wei, "fee limit"
        )
        self._max_priority_fee_per_gas_wei = self._positive_limit(
            max_priority_fee_per_gas_wei, "priority fee limit"
        )
        if self._max_priority_fee_per_gas_wei > self._max_fee_per_gas_wei:
            raise ValueError("priority fee limit exceeds fee limit")
        self._max_total_fee_wei = (
            None
            if max_total_fee_wei is None
            else self._positive_limit(max_total_fee_wei, "total fee limit")
        )
        if not callable(clock):
            raise TypeError("relayer clock is required")
        self._clock = clock
        self._submission_reconciler = HostedSubmissionReconciler(
            repository=repository,
            rpc=rpc,
            inspection_rpc=inspection_rpc,
            executor_address=self._executor_address,
            relayer_address=self._relayer_address,
            clock=self._clock,
            chain=self._chain,
            token=self._token,
            chain_id=self._chain_id,
        )

    @property
    def approval_verifier(self) -> ExecutionApprovalVerifier:
        """The Core authority verifier used for new executions."""

        return self._approval_verifier

    @property
    def execution_repository(self) -> ExecutionRepository:
        """The one durable execution repository shared with the public API."""

        return self._repository

    @property
    def chain(self) -> str:
        return self._chain

    @property
    def chain_id(self) -> int:
        return self._chain_id

    @property
    def token(self) -> str:
        return self._token

    def execute(self, intent: ExecutionIntent) -> HostedExecution:
        intent = ExecutionIntent.model_validate(intent, strict=True)
        self._require_bound_intent(intent)
        execution = self._repository.find_for_intent(intent)
        if execution is not None and execution.status in {
            ExecutionState.SUBMITTED,
            ExecutionState.SUBMISSION_UNKNOWN,
            ExecutionState.SUBMISSION_REJECTED,
            ExecutionState.CONFIRMED,
            ExecutionState.FINALIZED,
            ExecutionState.REVERTED,
            ExecutionState.EXPIRED,
            ExecutionState.RELEASED,
            ExecutionState.REORG_REVIEW,
        }:
            return execution
        try:
            self._approval_verifier.verify(intent)
        except Exception:
            raise RelayerExecutionError("Core execution approval is invalid") from None
        now = self._now()
        rpc_chain_checked = False
        if execution is None:
            if now >= intent.deadline:
                raise RelayerExecutionError("execution deadline has expired")
            self._require_rpc_chain()
            rpc_chain_checked = True
            chain_nonce = _quantity(
                self._rpc_read(
                    "eth_getTransactionCount", [self._relayer_address, "pending"]
                ),
                field="chain pending nonce",
            )
            chain_confirmed_nonce = _quantity(
                self._rpc_read(
                    "eth_getTransactionCount", [self._relayer_address, "latest"]
                ),
                field="chain confirmed nonce",
            )
            execution = self._repository.allocate_or_return(
                intent,
                chain_pending_nonce=chain_nonce,
                chain_confirmed_nonce=chain_confirmed_nonce,
                now=now,
            )
        if now >= execution.deadline:
            if execution.status in {
                ExecutionState.PREFLIGHT_APPROVED,
                ExecutionState.SIGNING,
            }:
                return self._repository.release_expired(
                    execution.execution_id,
                    now=now,
                )
            return execution
        if execution.status in {
            ExecutionState.PREFLIGHT_APPROVED,
            ExecutionState.SIGNING,
        }:
            if not rpc_chain_checked:
                self._require_rpc_chain()
            try:
                execution, acquired = self._repository.claim_signing(
                    execution.execution_id,
                    now=now,
                )
            except Exception:
                latest = self._repository.get_execution(execution.execution_id)
                if latest is None or latest.status in {
                    ExecutionState.PREFLIGHT_APPROVED,
                    ExecutionState.SIGNING,
                }:
                    raise
                return latest
            if not acquired:
                return execution
            execution = self._sign(execution)
        if execution.status is ExecutionState.SIGNED:
            submission_now = self._now()
            if submission_now >= execution.deadline:
                return execution
            if not rpc_chain_checked:
                self._require_rpc_chain()
            try:
                execution, acquired = self._repository.claim_submission(
                    execution.execution_id,
                    now=submission_now,
                )
            except PilotGateDenied:
                raise
            except Exception:
                latest = self._repository.get_execution(execution.execution_id)
                if latest is None:
                    raise
                return latest
            if not acquired:
                return execution
            return self._submit_signed(execution)
        return execution

    def rebroadcast_identical(self, execution_id: str) -> HostedExecution:
        return self._submission_reconciler.rebroadcast_identical(execution_id)

    def inspect_submission(self, execution_id: str) -> HostedExecution:
        return self._submission_reconciler.inspect_submission(execution_id)

    def _sign(self, execution: HostedExecution) -> HostedExecution:
        if execution.status is not ExecutionState.SIGNING:
            raise RelayerExecutionError("execution signing claim is unavailable")
        signing_claim_generation = execution.signing_claim_generation
        if signing_claim_generation <= 0:
            raise RelayerExecutionError("execution signing claim is unavailable")
        authorization = self._authorization(execution)
        digest = hash_execution(
            authorization,
            self._executor_address,
            chain_id=self._chain_id,
        )
        if "0x" + digest.hex() != execution.execution_digest:
            raise RelayerExecutionError("authorization digest does not match Core scope")
        try:
            execution_signature = self._execution_signer.sign_digest(digest)
        except Exception:
            raise RelayerExecutionError("execution signing is unavailable") from None
        calldata = encode_execute_calldata(authorization, execution_signature)
        gas_limit = self._gas_limit(calldata)
        priority_fee, max_fee = self._fee_quote()
        transaction = EIP1559Transaction(
            nonce=execution.relayer_nonce,
            max_priority_fee_per_gas=priority_fee,
            max_fee_per_gas=max_fee,
            gas_limit=gas_limit,
            to=self._executor_address,
            data=calldata,
            chain_id=self._chain_id,
        )
        total_fee_wei: int | None = None
        if self._max_total_fee_wei is not None:
            total_fee_wei = gas_limit * max_fee
            total_fee_wei += self._additional_fee_upper_bound(transaction)
            if total_fee_wei > self._max_total_fee_wei:
                raise RelayerExecutionError("total fee exceeds operator limit")
        pilot_policy = self._repository.pilot_policy
        if pilot_policy is not None:
            gas_reservation_now = self._now()
            if gas_reservation_now >= execution.deadline:
                raise RelayerExecutionError("execution deadline has expired")
            self._repository.reserve_pilot_gas(
                execution.execution_id,
                gas_cost_usd_micros=worst_case_gas_usd_micros(
                    1 if total_fee_wei is not None else gas_limit,
                    total_fee_wei if total_fee_wei is not None else max_fee,
                    pilot_policy.native_asset_usd_price_ceiling_micros,
                ),
                signing_claim_generation=signing_claim_generation,
                now=gas_reservation_now,
            )
        transaction_digest = eip1559_signing_hash(transaction)
        try:
            gas_signature = self._gas_signer.sign_digest(transaction_digest)
        except Exception:
            raise RelayerExecutionError("gas signing is unavailable") from None
        raw = encode_eip1559_signed(transaction, gas_signature)
        persist_now = self._now()
        if persist_now >= execution.deadline:
            raise RelayerExecutionError("execution deadline has expired")
        return self._repository.persist_signed_transaction(
            execution.execution_id,
            signature=execution_signature,
            raw_transaction=raw,
            signing_claim_generation=signing_claim_generation,
            unsigned_transaction_hash="0x" + transaction_digest.hex(),
            now=persist_now,
        )

    def _additional_fee_upper_bound(self, transaction: EIP1559Transaction) -> int:
        if self._chain_id not in {BASE_CHAIN_ID, BASE_SEPOLIA_CHAIN_ID}:
            return 0
        unsigned_size = len(encode_eip1559_unsigned(transaction))
        l1_fee_data = _GET_L1_FEE_UPPER_BOUND_SELECTOR + unsigned_size.to_bytes(32, "big")
        l1_fee = _uint256_word(
            self._rpc_read(
                "eth_call",
                [
                    {
                        "to": _BASE_GAS_PRICE_ORACLE,
                        "data": "0x" + l1_fee_data.hex(),
                    },
                    "latest",
                ],
            ),
            field="L1 fee upper bound",
        )
        operator_scalar = _uint256_word(
            self._rpc_read(
                "eth_call",
                [
                    {
                        "to": _BASE_L1_BLOCK,
                        "data": _OPERATOR_FEE_SCALAR_SELECTOR,
                    },
                    "latest",
                ],
            ),
            field="operator fee scalar",
        )
        operator_constant = _uint256_word(
            self._rpc_read(
                "eth_call",
                [
                    {
                        "to": _BASE_L1_BLOCK,
                        "data": _OPERATOR_FEE_CONSTANT_SELECTOR,
                    },
                    "latest",
                ],
            ),
            field="operator fee constant",
        )
        operator_fee = (
            transaction.gas_limit * operator_scalar // _OPERATOR_FEE_DECIMALS
        ) + operator_constant
        return l1_fee + operator_fee

    def _submit_signed(self, execution: HostedExecution) -> HostedExecution:
        if execution.status is not ExecutionState.SUBMISSION_UNKNOWN:
            raise RelayerExecutionError("execution submission claim is unavailable")
        known = self._lookup_exact_transaction(execution)
        if known:
            return self._repository.mark_submitted(
                execution.execution_id,
                now=self._now(),
            )
        if execution.raw_transaction is None or execution.raw_transaction_hash is None:
            raise RelayerExecutionError("persisted transaction is unavailable")
        send_now = self._now()
        if send_now >= execution.deadline:
            return execution
        try:
            returned_hash = self._rpc.call(
                "eth_sendRawTransaction", ["0x" + execution.raw_transaction.hex()]
            )
        except RpcSubmissionUnknown:
            return execution
        except RpcSubmissionRejected as exc:
            return self._repository.mark_submission_rejected(
                execution.execution_id,
                reason_code=exc.reason_code,
                now=send_now,
            )
        except Exception:
            return execution
        if returned_hash != execution.raw_transaction_hash:
            self._repository.mark_submission_unknown(
                execution.execution_id,
                now=send_now,
            )
            raise RelayerExecutionError("RPC returned a conflicting transaction hash")
        return self._repository.mark_submitted(
            execution.execution_id,
            now=send_now,
        )

    def _lookup_exact_transaction(self, execution: HostedExecution) -> bool:
        return self._submission_reconciler._lookup_exact_transaction(execution)

    def _gas_limit(self, calldata: bytes) -> int:
        estimate = _quantity(
            self._rpc_read(
                "eth_estimateGas",
                [
                    {
                        "from": self._relayer_address,
                        "to": self._executor_address,
                        "value": "0x0",
                        "data": "0x" + calldata.hex(),
                    }
                ],
            ),
            field="gas estimate",
        )
        if estimate <= 0 or estimate > self._max_gas_limit:
            raise RelayerExecutionError("gas estimate exceeds operator limit")
        buffered = estimate + max(1, estimate // 5)
        if buffered > self._max_gas_limit:
            raise RelayerExecutionError("gas estimate exceeds operator limit")
        return buffered

    def _fee_quote(self) -> tuple[int, int]:
        priority = _quantity(
            self._rpc_read("eth_maxPriorityFeePerGas", []),
            field="priority fee",
        )
        gas_price = _quantity(
            self._rpc_read("eth_gasPrice", []),
            field="fee quote",
        )
        if priority > self._max_priority_fee_per_gas_wei:
            raise RelayerExecutionError("priority fee exceeds operator limit")
        if gas_price <= 0 or gas_price > self._max_fee_per_gas_wei:
            raise RelayerExecutionError("fee quote exceeds operator limit")
        max_fee = gas_price * 2 + priority
        if max_fee > self._max_fee_per_gas_wei:
            raise RelayerExecutionError("fee quote exceeds operator limit")
        return priority, max_fee

    def _rpc_read(self, method: str, params: list[Any]) -> Any:
        return self._submission_reconciler._rpc_read(method, params)

    def _require_rpc_chain(self) -> None:
        self._submission_reconciler._require_rpc_chain()

    def _require_bound_intent(self, intent: ExecutionIntent) -> None:
        if intent.chain != self._chain or intent.token != self._token:
            raise RelayerExecutionError(
                "execution chain or token does not match operator configuration"
            )
        if intent.executor != self._executor_address:
            raise RelayerExecutionError("executor does not match operator configuration")
        if intent.relayer_address != self._relayer_address:
            raise RelayerExecutionError("relayer does not match operator configuration")
        authorization = self._authorization(intent)
        digest = "0x" + hash_execution(
            authorization,
            self._executor_address,
            chain_id=self._chain_id,
        ).hex()
        if digest != intent.execution_digest:
            raise RelayerExecutionError("authorization digest does not match Core scope")

    def _require_bound_execution(self, execution: HostedExecution) -> None:
        self._submission_reconciler._require_bound_execution(execution)

    def _authorization(self, execution: ExecutionIntent) -> ExecutionAuthorization:
        return self._submission_reconciler._authorization(execution)

    def _now(self) -> int:
        return self._submission_reconciler._now()

    @staticmethod
    def _positive_limit(value: object, field: str) -> int:
        if type(value) is not int or value <= 0:
            raise ValueError(f"{field} is invalid")
        return value
