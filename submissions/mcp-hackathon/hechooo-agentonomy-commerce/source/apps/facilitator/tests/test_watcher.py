from __future__ import annotations

from dataclasses import dataclass

import pytest

from execution_models import (
    BASE_CHAIN,
    BASE_USDC,
    POLYGON_CHAIN,
    POLYGON_USDC,
    ExecutionState,
)
from evm import encode_execute_calldata
from execution_repository import ExecutionConflict
from shared.hosted_facilitator_protocol import HOSTED_CHAIN_PROFILES
from watcher import HostedChainWatcher, WatcherConfigurationError


NOW = 2_000_000_000
TX_HASH = "0x" + "aa" * 32
RECEIPT_BLOCK_HASH = "0x" + "bb" * 32
SAFE_BLOCK_HASH = "0x" + "cc" * 32
OWNER = "0x" + "11" * 20
PAYEE = "0x" + "22" * 20
EXECUTOR = "0x" + "33" * 20
RELAYER = "0x" + "44" * 20
CAPABILITY_HASH = "0x" + "55" * 32
RESERVATION_HASH = "0x" + "66" * 32
SIGNATURE = bytes.fromhex("01" * 32 + "02" * 32 + "1b")


def make_watcher(repository, rpc, **overrides):
    values = {
        "executor_address": EXECUTOR,
        "chain": BASE_CHAIN,
        "token": BASE_USDC,
        "finality_boundary": "safe",
        "chain_id": 8453,
        "confirmation_depth": 2,
    }
    values.update(overrides)
    return HostedChainWatcher(repository, rpc, **values)


@dataclass
class FakeExecution:
    execution_id: str = "exec_1"
    status: ExecutionState = ExecutionState.SUBMITTED
    chain: str = BASE_CHAIN
    raw_transaction_hash: str | None = TX_HASH
    receipt_block_number: int | None = None
    receipt_block_hash: str | None = None
    receipt_status: int | None = None
    confirmations: int = 0
    safe_block_number: int | None = None
    safe_block_hash: str | None = None
    capability_hash: str = CAPABILITY_HASH
    reservation_hash: str = RESERVATION_HASH
    owner: str = OWNER
    payee: str = PAYEE
    token: str = BASE_USDC
    amount_atomic: str = "1000000"
    owner_nonce: int = 7
    deadline: int = NOW + 60
    signer_epoch: int = 1
    executor: str = EXECUTOR
    relayer_address: str = RELAYER
    relayer_nonce: int = 5


class FakeRpc:
    def __init__(self, responses: dict[tuple[str, str], object]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, list[object]]] = []

    def call(self, method: str, params: list[object]) -> object:
        self.calls.append((method, params))
        key = (method, repr(params))
        if key not in self.responses:
            raise AssertionError(f"unexpected RPC call: {method} {params!r}")
        response = self.responses[key]
        if isinstance(response, Exception):
            raise response
        return response


class FakeRepository:
    def __init__(self, execution: FakeExecution) -> None:
        self.execution = execution
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.strict_replay = False

    def get_execution(self, execution_id: str) -> FakeExecution | None:
        assert execution_id == self.execution.execution_id
        return self.execution

    def confirm(self, execution_id: str, **kwargs: object) -> FakeExecution:
        self.calls.append(("confirm", kwargs))
        assert execution_id == self.execution.execution_id
        if self.strict_replay and self.execution.status is ExecutionState.CONFIRMED:
            if kwargs["safe_block_hash"] != self.execution.safe_block_hash:
                raise RuntimeError("confirmation evidence changed")
        self.execution.status = ExecutionState.CONFIRMED
        self.execution.receipt_status = int(kwargs["receipt_status"])
        self.execution.receipt_block_number = int(kwargs["receipt_block_number"])
        self.execution.receipt_block_hash = str(kwargs["receipt_block_hash"])
        self.execution.confirmations = int(kwargs["confirmations"])
        self.execution.safe_block_number = int(kwargs["safe_block_number"])
        self.execution.safe_block_hash = str(kwargs["safe_block_hash"])
        self.execution.finality_boundary = str(kwargs["finality_boundary"])
        return self.execution

    def finalize(self, execution_id: str, **kwargs: object) -> FakeExecution:
        self.calls.append(("finalize", kwargs))
        assert execution_id == self.execution.execution_id
        self.execution.status = ExecutionState.FINALIZED
        return self.execution

    def revert(self, execution_id: str, **kwargs: object) -> FakeExecution:
        self.calls.append(("revert", kwargs))
        assert execution_id == self.execution.execution_id
        self.execution.status = ExecutionState.REVERTED
        self.execution.receipt_status = int(kwargs["receipt_status"])
        self.execution.receipt_block_number = int(kwargs["receipt_block_number"])
        self.execution.receipt_block_hash = str(kwargs["receipt_block_hash"])
        self.execution.confirmations = int(kwargs["confirmations"])
        self.execution.safe_block_number = int(kwargs["safe_block_number"])
        self.execution.safe_block_hash = str(kwargs["safe_block_hash"])
        self.execution.finality_boundary = str(kwargs["finality_boundary"])
        return self.execution

    def release_reverted(self, execution_id: str, **kwargs: object) -> FakeExecution:
        self.calls.append(("release_reverted", kwargs))
        assert execution_id == self.execution.execution_id
        self.execution.status = ExecutionState.RELEASED
        self.execution.released_at = NOW + 1
        self.execution.release_evidence = dict(kwargs["release_evidence"])
        return self.execution

    def mark_reorg_review(self, execution_id: str, **kwargs: object) -> FakeExecution:
        self.calls.append(("mark_reorg_review", kwargs))
        assert execution_id == self.execution.execution_id
        self.execution.status = ExecutionState.REORG_REVIEW
        return self.execution

    def release_expired(self, execution_id: str, **kwargs: object) -> FakeExecution:
        self.calls.append(("release_expired", kwargs))
        assert execution_id == self.execution.execution_id
        self.execution.status = ExecutionState.RELEASED
        return self.execution


def _word(value: int) -> str:
    return f"0x{value:064x}"


def _address_word(address: str) -> str:
    return "0x" + ("0" * 24) + address[2:].lower()


def _execution_input(execution: FakeExecution, *, relayer: str | None = None) -> str:
    calldata = encode_execute_calldata(
        {
            "capability_hash": execution.capability_hash,
            "reservation_hash": execution.reservation_hash,
            "owner": execution.owner,
            "payee": execution.payee,
            "token": execution.token,
            "amount": int(execution.amount_atomic),
            "nonce": execution.owner_nonce,
            "deadline": execution.deadline,
            "signer_epoch": execution.signer_epoch,
            "relayer": execution.relayer_address if relayer is None else relayer,
        },
        SIGNATURE,
    )
    return "0x" + calldata.hex()


def _payment_event(execution: FakeExecution) -> dict[str, object]:
    from eth_abi import encode

    topic = (
        "068133bf9486e7726dcaa3b2b03cb0dd7af09dbbf7f53efcc181881a885059fd"
    )
    data = encode(
        [
            "address",
            "address",
            "uint256",
            "uint256",
            "uint256",
            "address",
            "uint256",
            "address",
        ],
        [
            execution.payee,
            execution.token,
            int(execution.amount_atomic),
            execution.owner_nonce,
            execution.deadline,
            "0x" + "99" * 20,
            execution.signer_epoch,
            execution.relayer_address,
        ],
    )
    return {
        "address": execution.executor,
        "topics": [
            "0x" + topic,
            execution.capability_hash,
            execution.reservation_hash,
            _address_word(execution.owner),
        ],
        "data": "0x" + data.hex(),
    }


def _transfer_event(
    execution: FakeExecution,
    *,
    token: str | None = None,
    owner: str | None = None,
    payee: str | None = None,
    amount: int | None = None,
    topics: list[str] | None = None,
    data: str | None = None,
) -> dict[str, object]:
    transfer_topic = "ddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
    event_topics = [
        "0x" + transfer_topic,
        _address_word(execution.owner if owner is None else owner),
        _address_word(execution.payee if payee is None else payee),
    ] if topics is None else topics
    event_data = _word(
        int(execution.amount_atomic) if amount is None else amount
    ) if data is None else data
    return {
        "address": execution.token if token is None else token,
        "topics": event_topics,
        "data": event_data,
    }


def _responses(
    execution: FakeExecution,
    *,
    status: int = 1,
    event: bool = True,
    safe_timestamp: int = NOW + 1,
) -> dict[tuple[str, str], object]:
    profile = HOSTED_CHAIN_PROFILES[execution.chain]
    finality_boundary = profile.finality_boundary
    safe_block_number = 100 + profile.min_confirmation_depth
    boundary_block = hex(safe_block_number)
    tx = {
        "hash": TX_HASH,
        "blockHash": RECEIPT_BLOCK_HASH,
        "blockNumber": "0x64",
        "chainId": hex(profile.chain_id),
        "from": execution.relayer_address,
        "nonce": hex(execution.relayer_nonce),
        "type": "0x2",
        "value": "0x0",
        "to": execution.executor,
        "input": _execution_input(execution),
    }
    receipt = {
        "transactionHash": TX_HASH,
        "blockHash": RECEIPT_BLOCK_HASH,
        "blockNumber": "0x64",
        "status": hex(status),
        "logs": (
            [_payment_event(execution), _transfer_event(execution)]
            if event
            else []
        ),
    }
    safe = {
        "number": hex(safe_block_number),
        "hash": SAFE_BLOCK_HASH,
        "timestamp": hex(safe_timestamp),
    }
    receipt_block = {"number": "0x64", "hash": RECEIPT_BLOCK_HASH}
    return {
        ("eth_chainId", repr([])): hex(profile.chain_id),
        ("eth_getTransactionByHash", repr([TX_HASH])): tx,
        ("eth_getTransactionReceipt", repr([TX_HASH])): receipt,
        ("eth_getBlockByNumber", repr(["0x64", False])): receipt_block,
        ("eth_getBlockByNumber", repr([finality_boundary, False])): safe,
        ("eth_getCode", repr([execution.executor, boundary_block])): "0x6001",
        ("eth_getCode", repr([execution.token, boundary_block])): "0x6001",
    }


def _rpc_for(
    execution: FakeExecution,
    *,
    status: int = 1,
    event: bool = True,
    safe_timestamp: int = NOW + 1,
) -> FakeRpc:
    from eth_utils import keccak

    profile = HOSTED_CHAIN_PROFILES[execution.chain]
    boundary_block = hex(100 + profile.min_confirmation_depth)
    mapping_selector = "0x" + keccak(text="usedCapabilityHashes(bytes32)")[:4].hex()
    call_data = mapping_selector + execution.capability_hash[2:]
    values = _responses(
        execution,
        status=status,
        event=event,
        safe_timestamp=safe_timestamp,
    )
    values[("eth_call", repr([{"to": execution.executor, "data": call_data}, boundary_block]))] = _word(
        1 if status == 1 and event else 0
    )
    nonce_selector = "0x" + keccak(text="usedNonces(address,uint256)")[:4].hex()
    nonce_data = (
        nonce_selector
        + "0" * 24
        + execution.owner[2:].lower()
        + f"{execution.owner_nonce:064x}"
    )
    values[("eth_call", repr([{"to": execution.executor, "data": nonce_data}, boundary_block]))] = _word(
        1 if status == 1 and event else 0
    )
    return FakeRpc(values)


def _absent_transaction_rpc(execution: FakeExecution) -> FakeRpc:
    profile = HOSTED_CHAIN_PROFILES[execution.chain]
    return FakeRpc(
        {
            ("eth_chainId", repr([])): hex(profile.chain_id),
            ("eth_getTransactionByHash", repr([TX_HASH])): None,
            ("eth_getTransactionReceipt", repr([TX_HASH])): None,
        }
    )


def test_success_requires_independent_evidence_then_confirms_and_finalizes() -> None:
    execution = FakeExecution()
    repository = FakeRepository(execution)
    rpc = _rpc_for(execution)
    watcher = make_watcher(repository, rpc)

    result = watcher.watch(execution.execution_id)

    assert result.status is ExecutionState.FINALIZED
    assert [name for name, _ in repository.calls] == ["confirm", "finalize"]
    methods = [method for method, _ in rpc.calls]
    assert methods == [
        "eth_chainId",
        "eth_getTransactionByHash",
        "eth_getTransactionReceipt",
        "eth_getBlockByNumber",
        "eth_getBlockByNumber",
        "eth_getCode",
        "eth_getCode",
        "eth_call",
        "eth_call",
    ]


def test_success_persists_all_canonical_payment_evidence() -> None:
    execution = FakeExecution()
    repository = FakeRepository(execution)
    watcher = make_watcher(repository, _rpc_for(execution))

    result = watcher.watch(execution.execution_id)

    assert result.status is ExecutionState.FINALIZED
    confirm = next(kwargs for name, kwargs in repository.calls if name == "confirm")
    assert confirm["evidence"] == {
        "accepted_transfer": True,
        "boundary": "safe",
        "finality_boundary": "safe",
        "confirmations": 2,
        "receipt_block_number": 100,
        "safe_block_number": 102,
        "watcher_version": "hosted-chain-watcher-v1",
        "capability_used": True,
        "owner_nonce_used": True,
        "payment_event_found": True,
        "transfer_event_found": True,
        "finality_boundary_timestamp": NOW + 1,
    }


def test_code_and_replay_markers_use_the_observed_finality_block_number() -> None:
    execution = FakeExecution()
    repository = FakeRepository(execution)
    rpc = _rpc_for(execution)
    watcher = make_watcher(repository, rpc)

    result = watcher.watch(execution.execution_id)

    assert result.status is ExecutionState.FINALIZED
    boundary_block = "0x66"
    for method, params in rpc.calls:
        if method in {"eth_getCode", "eth_call"}:
            assert params[-1] == boundary_block


@pytest.mark.parametrize(
    "mutator,reason",
    [
        (
            lambda logs: logs.pop(),
            "accepted_transfer_unverified",
        ),
        (
            lambda logs: logs.append(logs[-1].copy()),
            "transfer_event_ambiguous",
        ),
        (
            lambda logs: logs.__setitem__(1, _transfer_event(FakeExecution(), amount=2)),
            "transfer_event_scope_mismatch",
        ),
        (
            lambda logs: logs.__setitem__(
                1,
                _transfer_event(
                    FakeExecution(),
                    topics=[
                        "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef",
                        _address_word(OWNER),
                    ],
                ),
            ),
            "transfer_event_topics_invalid",
        ),
        (
            lambda logs: logs.__setitem__(
                1,
                _transfer_event(FakeExecution(), data="0x01"),
            ),
            "transfer_event_data_invalid",
        ),
    ],
)
def test_success_requires_one_exact_canonical_transfer(mutator, reason: str) -> None:
    execution = FakeExecution()
    repository = FakeRepository(execution)
    rpc = _rpc_for(execution)
    receipt = rpc.responses[("eth_getTransactionReceipt", repr([TX_HASH]))]
    assert isinstance(receipt, dict)
    logs = receipt["logs"]
    assert isinstance(logs, list)
    mutator(logs)
    watcher = make_watcher(repository, rpc)

    result = watcher.watch(execution.execution_id)

    assert result.status is ExecutionState.SUBMITTED
    assert result.reason == reason
    assert repository.calls == []


@pytest.mark.parametrize("marker", ["capability", "nonce"])
def test_success_requires_both_replay_markers(
    marker: str,
) -> None:
    execution = FakeExecution()
    repository = FakeRepository(execution)
    rpc = _rpc_for(execution)
    from eth_utils import keccak

    if marker == "capability":
        selector = "0x" + keccak(text="usedCapabilityHashes(bytes32)")[:4].hex()
        data = selector + execution.capability_hash[2:]
    else:
        selector = "0x" + keccak(text="usedNonces(address,uint256)")[:4].hex()
        data = selector + "0" * 24 + execution.owner[2:] + f"{execution.owner_nonce:064x}"
    rpc.responses[("eth_call", repr([{"to": execution.executor, "data": data}, "0x66"]))] = _word(0)
    watcher = make_watcher(repository, rpc)

    result = watcher.watch(execution.execution_id)

    assert result.status is ExecutionState.SUBMITTED
    assert result.reason == "accepted_transfer_unverified"
    assert repository.calls == []


def test_failed_receipt_with_transfer_cannot_be_released() -> None:
    execution = FakeExecution()
    repository = FakeRepository(execution)
    watcher = make_watcher(repository, _rpc_for(execution, status=0, event=True))

    result = watcher.watch(execution.execution_id)

    assert result.status is ExecutionState.SUBMITTED
    assert result.reason == "failed_receipt_transfer_ambiguous"
    assert repository.calls == []


def test_reverted_execution_remains_reserved_before_deadline() -> None:
    execution = FakeExecution(status=ExecutionState.REVERTED)
    execution.receipt_status = 0
    execution.receipt_block_number = 100
    execution.receipt_block_hash = RECEIPT_BLOCK_HASH
    execution.confirmations = 2
    execution.safe_block_number = 102
    execution.safe_block_hash = SAFE_BLOCK_HASH
    repository = FakeRepository(execution)
    watcher = make_watcher(
        repository,
        _rpc_for(execution, status=0, event=False, safe_timestamp=execution.deadline - 1),
    )

    result = watcher.watch(execution.execution_id)

    assert result.status is ExecutionState.REVERTED
    assert result.action == "unchanged"
    assert result.reason == "authorization_replay_window"
    assert repository.calls == []


def test_reverted_execution_releases_at_deadline_with_immutable_proof() -> None:
    execution = FakeExecution(status=ExecutionState.REVERTED)
    execution.receipt_status = 0
    execution.receipt_block_number = 100
    execution.receipt_block_hash = RECEIPT_BLOCK_HASH
    execution.confirmations = 2
    execution.safe_block_number = 102
    execution.safe_block_hash = SAFE_BLOCK_HASH
    repository = FakeRepository(execution)
    watcher = make_watcher(
        repository,
        _rpc_for(execution, status=0, event=False, safe_timestamp=execution.deadline),
    )

    result = watcher.watch(execution.execution_id)

    assert result.status is ExecutionState.RELEASED
    release = next(kwargs for name, kwargs in repository.calls if name == "release_reverted")
    assert release["release_evidence"] == {
        "receipt_status": 0,
        "canonical_receipt": True,
        "finality_boundary_timestamp": execution.deadline,
        "capability_used": False,
        "owner_nonce_used": False,
        "payment_event_found": False,
        "transfer_event_found": False,
    }


@pytest.mark.parametrize("marker", ["capability", "nonce"])
def test_reverted_execution_is_not_released_if_marker_was_consumed(marker: str) -> None:
    execution = FakeExecution(status=ExecutionState.REVERTED)
    execution.receipt_status = 0
    execution.receipt_block_number = 100
    execution.receipt_block_hash = RECEIPT_BLOCK_HASH
    execution.confirmations = 2
    execution.safe_block_number = 102
    execution.safe_block_hash = SAFE_BLOCK_HASH
    repository = FakeRepository(execution)
    rpc = _rpc_for(
        execution,
        status=0,
        event=False,
        safe_timestamp=execution.deadline,
    )
    from eth_utils import keccak

    if marker == "capability":
        selector = "0x" + keccak(text="usedCapabilityHashes(bytes32)")[:4].hex()
        data = selector + execution.capability_hash[2:]
    else:
        selector = "0x" + keccak(text="usedNonces(address,uint256)")[:4].hex()
        data = selector + "0" * 24 + execution.owner[2:] + f"{execution.owner_nonce:064x}"
    rpc.responses[("eth_call", repr([{"to": execution.executor, "data": data}, "0x66"]))] = _word(1)
    watcher = make_watcher(repository, rpc)

    result = watcher.watch(execution.execution_id)

    assert result.status is ExecutionState.REVERTED
    assert result.action == "unchanged"
    assert repository.calls == []


@pytest.mark.parametrize(
    "state",
    [ExecutionState.PREFLIGHT_APPROVED, ExecutionState.SIGNING],
)
def test_unsigned_expired_work_is_released_without_rpc(state: ExecutionState) -> None:
    execution = FakeExecution(status=state, raw_transaction_hash=None, deadline=NOW - 1)
    repository = FakeRepository(execution)
    rpc = FakeRpc({})
    watcher = make_watcher(repository, rpc)

    result = watcher.watch(execution.execution_id)

    assert result.status is ExecutionState.RELEASED
    assert result.action == "released"
    assert result.reason == "deadline_expired"
    assert [name for name, _ in repository.calls] == ["release_expired"]
    assert rpc.calls == []


def test_unsigned_active_work_remains_reserved_without_rpc() -> None:
    execution = FakeExecution(
        status=ExecutionState.SIGNING,
        raw_transaction_hash=None,
        deadline=NOW + 60,
    )

    class ActiveRepository(FakeRepository):
        def release_expired(self, execution_id: str, **kwargs: object) -> FakeExecution:
            self.calls.append(("release_expired", kwargs))
            raise ExecutionConflict("execution deadline has not expired")

    repository = ActiveRepository(execution)
    rpc = FakeRpc({})
    watcher = make_watcher(repository, rpc)

    result = watcher.watch(execution.execution_id)

    assert result.status is ExecutionState.SIGNING
    assert result.action == "unchanged"
    assert result.reason == "authorization_active"
    assert rpc.calls == []


def test_polygon_uses_finalized_boundary_and_persists_it() -> None:
    execution = FakeExecution(chain=POLYGON_CHAIN, token=POLYGON_USDC)
    repository = FakeRepository(execution)
    watcher = make_watcher(
        repository,
        _rpc_for(execution),
        chain=POLYGON_CHAIN,
        token=POLYGON_USDC,
        chain_id=137,
        finality_boundary="finalized",
        confirmation_depth=3,
    )

    result = watcher.watch(execution.execution_id)

    assert result.status is ExecutionState.FINALIZED
    assert result.finality_boundary == "finalized"
    assert [name for name, _ in repository.calls] == ["confirm", "finalize"]
    assert all(
        kwargs["finality_boundary"] == "finalized"
        for _, kwargs in repository.calls
    )


def test_safe_boundary_rejects_executor_code_hash_mismatch() -> None:
    execution = FakeExecution()
    repository = FakeRepository(execution)
    rpc = _rpc_for(execution)
    watcher = make_watcher(
        repository,
        rpc,
        executor_address=EXECUTOR,
        executor_code_hash="0x" + "99" * 32,
    )

    result = watcher.watch(execution.execution_id)

    assert result.status is ExecutionState.SUBMITTED
    assert result.reason == "executor_code_mismatch"
    assert repository.calls == []


def test_failed_receipt_reverts_only_when_no_accepted_transfer() -> None:
    execution = FakeExecution()
    repository = FakeRepository(execution)
    watcher = make_watcher(
        repository, _rpc_for(execution, status=0, event=False), executor_address=EXECUTOR
    )

    result = watcher.watch(execution.execution_id)

    assert result.status is ExecutionState.REVERTED
    assert [name for name, _ in repository.calls] == ["revert"]


@pytest.mark.parametrize(
    "mutator",
    [
        lambda execution: setattr(execution, "amount_atomic", "1000001"),
        lambda execution: setattr(execution, "reservation_hash", "0x" + "67" * 32),
    ],
)
def test_scope_mismatch_fails_closed(mutator) -> None:
    execution = FakeExecution()
    repository = FakeRepository(execution)
    watcher = make_watcher(repository, _rpc_for(execution))
    mutator(execution)

    result = watcher.watch(execution.execution_id)

    assert result.status is ExecutionState.SUBMITTED
    assert repository.calls == []


def test_success_without_matching_event_fails_closed() -> None:
    execution = FakeExecution()
    repository = FakeRepository(execution)
    watcher = make_watcher(
        repository, _rpc_for(execution, status=1, event=False), executor_address=EXECUTOR
    )

    result = watcher.watch(execution.execution_id)

    assert result.status is ExecutionState.SUBMITTED
    assert repository.calls == []


def test_signed_relayer_must_match_stored_relayer() -> None:
    execution = FakeExecution()
    repository = FakeRepository(execution)
    rpc = _rpc_for(execution)
    tx = rpc.responses[("eth_getTransactionByHash", repr([TX_HASH]))]
    assert isinstance(tx, dict)
    tx["input"] = _execution_input(execution, relayer="0x" + "66" * 20)
    watcher = make_watcher(repository, rpc)

    result = watcher.watch(execution.execution_id)

    assert result.status is ExecutionState.SUBMITTED
    assert result.reason == "transaction_scope_mismatch"
    assert repository.calls == []


def test_failed_receipt_with_used_capability_does_not_release() -> None:
    execution = FakeExecution()
    repository = FakeRepository(execution)
    rpc = _rpc_for(execution, status=0, event=False)
    from eth_utils import keccak

    call_data = "0x" + keccak(text="usedCapabilityHashes(bytes32)")[:4].hex() + execution.capability_hash[2:]
    rpc.responses[("eth_call", repr([{"to": execution.executor, "data": call_data}, "0x66"]))] = _word(1)
    watcher = make_watcher(repository, rpc)

    result = watcher.watch(execution.execution_id)

    assert result.status is ExecutionState.SUBMITTED
    assert repository.calls == []


def test_unsafe_or_noncanonical_evidence_fails_closed() -> None:
    execution = FakeExecution()
    repository = FakeRepository(execution)
    rpc = _rpc_for(execution)
    rpc.responses[("eth_getBlockByNumber", repr(["0x64", False]))] = {
        "number": "0x64",
        "hash": "0x" + "dd" * 32,
    }
    watcher = make_watcher(repository, rpc)

    result = watcher.watch(execution.execution_id)

    assert result.status is ExecutionState.SUBMITTED
    assert repository.calls == []


def test_finalized_canonical_change_enters_reorg_review() -> None:
    execution = FakeExecution(status=ExecutionState.FINALIZED)
    execution.receipt_block_number = 100
    execution.receipt_block_hash = RECEIPT_BLOCK_HASH
    execution.safe_block_number = 102
    execution.safe_block_hash = SAFE_BLOCK_HASH
    repository = FakeRepository(execution)
    rpc = _rpc_for(execution)
    rpc.responses[("eth_getBlockByNumber", repr(["0x64", False]))] = {
        "number": "0x64",
        "hash": "0x" + "dd" * 32,
    }
    watcher = make_watcher(repository, rpc)

    result = watcher.watch(execution.execution_id)

    assert result.status is ExecutionState.REORG_REVIEW
    assert [name for name, _ in repository.calls] == ["mark_reorg_review"]


def test_polygon_finalized_canonical_change_enters_reorg_review() -> None:
    execution = FakeExecution(
        status=ExecutionState.FINALIZED,
        chain=POLYGON_CHAIN,
        token=POLYGON_USDC,
    )
    execution.receipt_block_number = 100
    execution.receipt_block_hash = RECEIPT_BLOCK_HASH
    execution.safe_block_number = 103
    execution.safe_block_hash = SAFE_BLOCK_HASH
    repository = FakeRepository(execution)
    rpc = _rpc_for(execution)
    rpc.responses[("eth_getBlockByNumber", repr(["0x64", False]))] = {
        "number": "0x64",
        "hash": "0x" + "dd" * 32,
    }
    watcher = make_watcher(
        repository,
        rpc,
        chain=POLYGON_CHAIN,
        token=POLYGON_USDC,
        chain_id=137,
        finality_boundary="finalized",
        confirmation_depth=3,
    )

    result = watcher.watch(execution.execution_id)

    assert result.status is ExecutionState.REORG_REVIEW
    assert result.finality_boundary == "finalized"
    assert [name for name, _ in repository.calls] == ["mark_reorg_review"]


def test_polygon_watcher_rejects_stored_safe_boundary() -> None:
    execution = FakeExecution(chain=POLYGON_CHAIN, token=POLYGON_USDC)
    execution.finality_boundary = "safe"
    repository = FakeRepository(execution)
    watcher = make_watcher(
        repository,
        _rpc_for(execution),
        chain=POLYGON_CHAIN,
        token=POLYGON_USDC,
        chain_id=137,
        finality_boundary="finalized",
        confirmation_depth=3,
    )

    result = watcher.watch(execution.execution_id)

    assert result.status is ExecutionState.SUBMITTED
    assert result.reason == "finality_boundary_mismatch"
    assert repository.calls == []


def test_confirmed_execution_replays_evidence_before_finalizing() -> None:
    execution = FakeExecution(status=ExecutionState.CONFIRMED)
    repository = FakeRepository(execution)
    watcher = make_watcher(repository, _rpc_for(execution))

    result = watcher.watch(execution.execution_id)

    assert result.status is ExecutionState.FINALIZED
    assert [name for name, _ in repository.calls] == ["confirm", "finalize"]


def test_payment_event_topic_is_fixed_to_executor_abi() -> None:
    from watcher import _PAYMENT_EVENT_TOPIC

    assert _PAYMENT_EVENT_TOPIC == (
        "0x068133bf9486e7726dcaa3b2b03cb0dd7af09dbbf7f53efcc181881a885059fd"
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("from", "0x" + "55" * 20),
        ("nonce", "0x6"),
        ("type", "0x1"),
        ("value", "0x1"),
    ],
)
def test_transaction_envelope_mismatch_fails_closed(field: str, value: str) -> None:
    execution = FakeExecution()
    repository = FakeRepository(execution)
    rpc = _rpc_for(execution)
    rpc.responses[("eth_getTransactionByHash", repr([TX_HASH]))][field] = value
    watcher = make_watcher(repository, rpc)

    result = watcher.watch(execution.execution_id)

    assert result.status is ExecutionState.SUBMITTED
    assert repository.calls == []


def test_invalid_executor_configuration_is_secret_free() -> None:
    with pytest.raises(WatcherConfigurationError, match="executor"):
        make_watcher(
            FakeRepository(FakeExecution()),
            _rpc_for(FakeExecution()),
            executor_address="bad",
        )


def test_confirmed_evidence_change_is_rejected_before_finalize() -> None:
    execution = FakeExecution(status=ExecutionState.CONFIRMED)
    execution.safe_block_hash = "0x" + "dd" * 32
    repository = FakeRepository(execution)
    repository.strict_replay = True
    watcher = make_watcher(repository, _rpc_for(execution))

    result = watcher.watch(execution.execution_id)

    assert result.status is ExecutionState.CONFIRMED
    assert [name for name, _ in repository.calls] == ["confirm"]


def test_finalized_failed_receipt_is_reorg_reviewed() -> None:
    execution = FakeExecution(status=ExecutionState.FINALIZED)
    execution.receipt_block_number = 100
    execution.receipt_block_hash = RECEIPT_BLOCK_HASH
    execution.safe_block_number = 102
    execution.safe_block_hash = SAFE_BLOCK_HASH
    repository = FakeRepository(execution)
    watcher = make_watcher(
        repository, _rpc_for(execution, status=0, event=False), executor_address=EXECUTOR
    )

    result = watcher.watch(execution.execution_id)

    assert result.status is ExecutionState.REORG_REVIEW
    assert [name for name, _ in repository.calls] == ["mark_reorg_review"]


def test_rpc_failure_is_secret_free_and_does_not_mutate() -> None:
    execution = FakeExecution()
    repository = FakeRepository(execution)
    rpc = FakeRpc({("eth_chainId", repr([])): RuntimeError("https://secret-token@example/rpc")})
    watcher = make_watcher(repository, rpc)

    result = watcher.watch(execution.execution_id)

    assert result.status is ExecutionState.SUBMITTED
    assert repository.calls == []
    assert "secret-token" not in repr(watcher)
    assert "secret-token" not in repr(result)


def test_rejected_submission_remains_recoverable_after_safe_chain_deadline() -> None:
    execution = FakeExecution(status=ExecutionState.SUBMISSION_REJECTED)
    repository = FakeRepository(execution)
    rpc = _absent_transaction_rpc(execution)
    watcher = make_watcher(repository, rpc)

    result = watcher.watch(execution.execution_id)

    assert result.status is ExecutionState.SUBMISSION_REJECTED
    assert result.action == "unchanged"
    assert result.reason == "evidence_unavailable"
    assert repository.calls == []


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("executor", "0x" + "77" * 20),
        ("token", "0x" + "88" * 20),
    ],
)
def test_rejected_observation_requires_exact_executor_and_token_scope(
    field: str,
    value: str,
) -> None:
    execution = FakeExecution(status=ExecutionState.SUBMISSION_REJECTED)
    setattr(execution, field, value)
    repository = FakeRepository(execution)
    watcher = make_watcher(
        repository,
        _absent_transaction_rpc(execution),
        executor_address=EXECUTOR,
    )

    result = watcher.watch(execution.execution_id)

    assert result.status is ExecutionState.SUBMISSION_REJECTED
    assert result.reason.endswith("scope_mismatch")
    assert repository.calls == []
