from __future__ import annotations

from datetime import UTC, datetime

import pytest

from services.account_service.repository import AccountRepository
from services.account_service.schemas import AssetAllowance, WalletIdentity
from services.account_service.service import AccountService
from services.audit_service.service import AuditService


NOW = datetime(2026, 7, 15, 12, 0, tzinfo=UTC)
POLYGON = "eip155:137"
BASE = "eip155:8453"
OWNER = "0x" + "11" * 20
TOKEN = "0x3c499c542cef5e3811e1192ce70d8cc03d5c3359"
BASE_TOKEN = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"
SPENDER = "0x" + "33" * 20
TX_HASH = "0x" + "44" * 32
APPROVE_SELECTOR = "095ea7b3"


def approve_calldata(spender: str = SPENDER, amount: int = 2_000_000) -> str:
    return "0x" + APPROVE_SELECTOR + ("0" * 24) + spender[2:] + amount.to_bytes(32, "big").hex()


class FakeRpc:
    def __init__(self) -> None:
        self.calls = []
        self.network = POLYGON
        self.chain_id = 137
        self.accept_all_networks = False
        self.current_block = 102
        self.allowance = 2_000_000
        self.fail_eth_call = False
        self.receipt = {
            "transactionHash": TX_HASH,
            "status": "0x1",
            "blockNumber": "0x64",
            "blockHash": "0x" + "ab" * 32,
        }
        self.transaction = {
            "hash": TX_HASH,
            "from": OWNER,
            "to": TOKEN,
            "input": approve_calldata(),
            "blockNumber": "0x64",
            "blockHash": "0x" + "ab" * 32,
        }

    def __call__(self, network, method, params):
        self.calls.append((network, method, params))
        if network != self.network and not self.accept_all_networks:
            return None
        if method == "eth_chainId":
            return hex(self.chain_id)
        if method == "eth_getTransactionReceipt":
            return self.receipt
        if method == "eth_getTransactionByHash":
            return self.transaction
        if method == "eth_blockNumber":
            return hex(self.current_block)
        if method == "eth_call":
            if self.fail_eth_call:
                raise RuntimeError("rpc unavailable")
            return hex(self.allowance)
        raise AssertionError(f"unexpected method {method}")


@pytest.fixture
def allowance_context(tmp_path):
    repository = AccountRepository(f"sqlite+pysqlite:///{tmp_path / 'allowances.db'}")
    identity = WalletIdentity(
        wallet_identity_id="wallet_identity_1",
        user_id="user_1",
        wallet_address=OWNER,
        status="active",
        proof_hash="proof",
        verified_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )
    repository.save_wallet_identity(identity)
    rpc = FakeRpc()
    service = AccountService(
        repository,
        domain="account.clink.example",
        clock=lambda: NOW,
        rpc_transport=rpc,
        network_configs={
            POLYGON: {
                "chain_id": 137,
                "required_confirmations": 3,
                "token_symbol": "USDC",
                "token_decimals": 6,
                "token_address": TOKEN,
            },
            BASE: {
                "chain_id": 8453,
                "required_confirmations": 2,
                "token_symbol": "USDC",
                "token_decimals": 6,
                "token_address": BASE_TOKEN,
            },
        },
    )
    return service, repository, rpc, identity


def verify(service, identity, **updates) -> AssetAllowance:
    values = {
        "wallet_identity_id": identity.wallet_identity_id,
        "network": POLYGON,
        "token_address": TOKEN,
        "spender_address": SPENDER,
        "allowance_tx_hash": TX_HASH,
    }
    values.update(updates)
    return service.verify_asset_allowance(**values)


def test_verifies_exact_approve_proof_and_is_idempotent(allowance_context):
    service, repository, rpc, identity = allowance_context

    allowance = verify(service, identity)
    repeated = verify(service, identity)

    assert repeated == allowance
    assert allowance.approved_amount_atomic == 2_000_000
    assert allowance.observed_allowance_atomic == 2_000_000
    assert allowance.confirmed_block == 100
    assert allowance.status == "active"
    assert repository.asset_allowances(identity.wallet_identity_id) == [allowance]
    assert {network for network, _method, _params in rpc.calls} == {POLYGON}


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda rpc: rpc.receipt.update(status="0x0"), "receipt was not successful"),
        (lambda rpc: rpc.transaction.update(from_="unused", **{"from": "0x" + "99" * 20}), "sender does not match wallet identity"),
        (lambda rpc: rpc.transaction.update(to="0x" + "99" * 20), "token does not match"),
        (lambda rpc: rpc.transaction.update(input="0xdeadbeef" + approve_calldata()[10:]), "approve selector"),
        (lambda rpc: rpc.transaction.update(input=approve_calldata("0x" + "99" * 20)), "spender does not match"),
        (lambda rpc: rpc.transaction.update(input=approve_calldata() + "00"), "approve calldata length"),
        (lambda rpc: setattr(rpc, "current_block", 101), "insufficient confirmations"),
        (lambda rpc: rpc.transaction.update(blockNumber="0x63"), "transaction block does not match receipt"),
    ],
)
def test_rejects_invalid_chain_proof(allowance_context, mutation, message):
    service, repository, rpc, identity = allowance_context
    mutation(rpc)

    with pytest.raises(ValueError, match=message):
        verify(service, identity)

    assert repository.asset_allowances(identity.wallet_identity_id) == []


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("token_address", "0x1234", "EVM address"),
        ("spender_address", "not-an-address", "EVM address"),
        ("allowance_tx_hash", "0x1234", "transaction hash"),
    ],
)
def test_rejects_malformed_inputs(allowance_context, field, value, message):
    service, _repository, _rpc, identity = allowance_context

    with pytest.raises(ValueError, match=message):
        verify(service, identity, **{field: value})


def test_polygon_proof_cannot_create_base_allowance(allowance_context):
    service, repository, rpc, identity = allowance_context
    rpc.accept_all_networks = True

    with pytest.raises(ValueError, match="RPC chain id does not match"):
        verify(service, identity, network=BASE, token_address=BASE_TOKEN)

    assert repository.asset_allowances(identity.wallet_identity_id) == []
    assert rpc.calls[0][0] == BASE


def test_conflicting_proof_for_existing_scope_is_rejected(allowance_context):
    service, _repository, rpc, identity = allowance_context
    verify(service, identity)
    rpc.transaction["hash"] = "0x" + "55" * 32
    rpc.receipt["transactionHash"] = rpc.transaction["hash"]

    with pytest.raises(ValueError, match="conflicts with existing allowance"):
        verify(service, identity, allowance_tx_hash=rpc.transaction["hash"])


def test_newer_approval_for_existing_scope_updates_same_allowance(allowance_context):
    service, repository, rpc, identity = allowance_context
    rpc.allowance = 500_000
    rpc.transaction["input"] = approve_calldata(amount=500_000)
    original = verify(service, identity)

    newer_hash = "0x" + "66" * 32
    rpc.current_block = 103
    rpc.allowance = 25_000_000
    rpc.receipt.update(transactionHash=newer_hash, blockNumber="0x65")
    rpc.transaction.update(
        hash=newer_hash,
        input=approve_calldata(amount=25_000_000),
        blockNumber="0x65",
    )

    updated = verify(service, identity, allowance_tx_hash=newer_hash)

    assert updated.asset_allowance_id == original.asset_allowance_id
    assert updated.allowance_tx_hash == newer_hash
    assert updated.approved_amount_atomic == 25_000_000
    assert updated.observed_allowance_atomic == 25_000_000
    assert repository.asset_allowances(identity.wallet_identity_id) == [updated]


def test_repeated_identical_proof_atomically_updates_latest_chain_observation(
    allowance_context,
):
    service, repository, rpc, identity = allowance_context
    original = verify(service, identity)
    checked_at = NOW.replace(hour=13)
    service.clock = lambda: checked_at
    rpc.allowance = 0

    repeated = verify(service, identity)

    assert repeated.asset_allowance_id == original.asset_allowance_id
    assert repeated.status == "revoked"
    assert repeated.observed_allowance_atomic == 0
    assert repeated.last_chain_check_at == checked_at
    assert repeated.updated_at == checked_at
    assert repository.asset_allowances(identity.wallet_identity_id) == [repeated]


def test_rejects_zero_amount_approve_proof(allowance_context):
    service, repository, rpc, identity = allowance_context
    rpc.transaction["input"] = approve_calldata(amount=0)
    rpc.allowance = 0

    with pytest.raises(ValueError, match="approved amount must be positive"):
        verify(service, identity)

    assert repository.asset_allowances(identity.wallet_identity_id) == []


def test_explicit_empty_network_configs_fail_allowance_verification_closed(
    allowance_context,
):
    _service, repository, rpc, identity = allowance_context
    service = AccountService(
        repository,
        domain="account.clink.example",
        clock=lambda: NOW,
        rpc_transport=rpc,
        network_configs={},
    )

    with pytest.raises(ValueError, match="unsupported asset allowance network"):
        verify(service, identity)


def test_refresh_keeps_positive_partial_allowance_active_then_revokes_and_marks_stale(
    allowance_context,
):
    service, repository, rpc, identity = allowance_context
    allowance = verify(service, identity)

    rpc.allowance = 1_500_000
    partial = service.refresh_asset_allowance(allowance.asset_allowance_id)
    assert partial.status == "active"
    assert partial.observed_allowance_atomic == 1_500_000

    rpc.allowance = 0
    revoked = service.refresh_asset_allowance(allowance.asset_allowance_id)
    assert revoked.status == "revoked"
    assert revoked.observed_allowance_atomic == 0

    rpc.fail_eth_call = True
    stale = service.refresh_asset_allowance(allowance.asset_allowance_id)
    assert stale.status == "stale"
    assert stale.observed_allowance_atomic == 0
    events = AuditService(database_url=str(repository.engine.url)).get_trail(
        user_id=identity.user_id
    ).events
    assert [event.event_type for event in events] == [
        "allowance_verified",
        "allowance_refreshed",
        "allowance_refreshed",
        "allowance_refreshed",
    ]
    assert [event.payload["status"] for event in events] == [
        "active",
        "active",
        "revoked",
        "stale",
    ]


def test_models_reject_negative_atomic_amounts(allowance_context):
    service, _repository, _rpc, identity = allowance_context
    allowance = verify(service, identity)

    with pytest.raises(ValueError, match="greater than or equal to 0"):
        allowance.model_copy(update={"observed_allowance_atomic": -1}).model_validate(
            allowance.model_copy(update={"observed_allowance_atomic": -1}).model_dump()
        )
