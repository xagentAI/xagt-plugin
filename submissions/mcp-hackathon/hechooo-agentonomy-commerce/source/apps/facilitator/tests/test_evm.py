from __future__ import annotations

import pytest

from evm import (
    BASE_CHAIN_ID,
    BASE_SEPOLIA_CHAIN_ID,
    BASE_SEPOLIA_USDC,
    BASE_USDC,
    POLYGON_AMOY_CHAIN_ID,
    POLYGON_AMOY_USDC,
    POLYGON_CHAIN_ID,
    POLYGON_USDC,
    EIP1559Transaction,
    EvmEncodingError,
    ExecutionAuthorization,
    encode_execute_calldata,
    domain_separator,
    hash_execution,
    raw_transaction_hash,
)


EXECUTOR = "0x1111111111111111111111111111111111111111"
DIGEST_FIXTURE_EXECUTOR = "0xD290aaCF3E0DbF6bBEBA9D900C6bcdcBDb05a182"
CAPABILITY = bytes.fromhex("11" * 32)
RESERVATION = bytes.fromhex("22" * 32)
OWNER = "0x3333333333333333333333333333333333333333"
PAYEE = "0x4444444444444444444444444444444444444444"
RELAYER = "0x5555555555555555555555555555555555555555"
SIGNATURE = bytes(range(1, 65)) + bytes([27])


def authorization(**overrides: object) -> ExecutionAuthorization:
    values: dict[str, object] = {
        "capability_hash": CAPABILITY,
        "reservation_hash": RESERVATION,
        "owner": OWNER,
        "payee": PAYEE,
        "token": BASE_USDC,
        "amount": 1_250_000,
        "nonce": 7,
        "deadline": 1_700_000_000,
        "signer_epoch": 3,
        "relayer": RELAYER,
    }
    values.update(overrides)
    return ExecutionAuthorization(**values)


def test_execution_digest_matches_solidity_vector_and_binds_signer_epoch() -> None:
    execution = authorization()

    assert hash_execution(execution, EXECUTOR).hex() == (
        "5fa3f358908b8dfa68116f4d7b1efac15962d901a45b49c7770ddf6657c5a895"
    )
    assert hash_execution(
        ExecutionAuthorization(**{**execution.__dict__, "signer_epoch": 4}), EXECUTOR
    ) != hash_execution(execution, EXECUTOR)


def test_execution_digest_matches_fixed_solidity_contract_fixture() -> None:
    execution = authorization()

    assert domain_separator(DIGEST_FIXTURE_EXECUTOR).hex() == (
        "ce47a2de22c2ebf0c7d7561981f6409eb675f3cb1e83e1d4b3b0b9ea7102e30e"
    )
    assert hash_execution(execution, DIGEST_FIXTURE_EXECUTOR).hex() == (
        "18bdf69c696d3376992b946974135bb28b41fee3d59e98f107ba5e5979be8e02"
    )


def test_execution_digest_binds_the_signed_relayer() -> None:
    execution = authorization(relayer=RELAYER)

    assert execution.relayer == RELAYER.lower()
    assert hash_execution(execution, EXECUTOR).hex() == (
        "5fa3f358908b8dfa68116f4d7b1efac15962d901a45b49c7770ddf6657c5a895"
    )
    assert hash_execution(
        authorization(relayer="0x6666666666666666666666666666666666666666"), EXECUTOR
    ) != hash_execution(execution, EXECUTOR)


def test_execution_authorization_rejects_zero_relayer() -> None:
    with pytest.raises(EvmEncodingError, match="relayer"):
        authorization(relayer="0x" + "00" * 20)


@pytest.mark.parametrize(
    ("chain_id", "token", "expected_digest"),
    [
        (
            BASE_CHAIN_ID,
            BASE_USDC,
            "5fa3f358908b8dfa68116f4d7b1efac15962d901a45b49c7770ddf6657c5a895",
        ),
        (
            POLYGON_CHAIN_ID,
            POLYGON_USDC,
            "f5b8f20ba4eb5dbe575588a798a8548a7b414f60f587ee7d528cac3abe0604c0",
        ),
        (
            BASE_SEPOLIA_CHAIN_ID,
            BASE_SEPOLIA_USDC,
            "95ee4ae3ec205c831599e902415c692480b06a95cf6e83c132ccc77b831685a0",
        ),
        (
            POLYGON_AMOY_CHAIN_ID,
            POLYGON_AMOY_USDC,
            "f4711be9f269969b48fe7a26901528e68b15f8c7696c5f08cbdadfae5d238062",
        ),
    ],
)
def test_execution_authorization_accepts_each_approved_chain_token_pair(
    chain_id: int, token: str, expected_digest: str
) -> None:
    execution = authorization(chain_id=chain_id, token=token)

    assert execution.chain_id == chain_id
    assert execution.token.lower() == token.lower()
    assert hash_execution(execution, EXECUTOR).hex() == expected_digest


def test_execution_authorization_rejects_unsupported_chain_and_mismatched_token() -> None:
    with pytest.raises(EvmEncodingError):
        authorization(chain_id=1, token=BASE_USDC)
    with pytest.raises(EvmEncodingError):
        authorization(chain_id=POLYGON_CHAIN_ID, token=BASE_USDC)


def test_executor_domain_name_is_agentonomy() -> None:
    from evm import EXECUTOR_EIP712_NAME

    assert EXECUTOR_EIP712_NAME == "Agentonomy USDC Executor"


def test_execute_calldata_matches_fixed_abi_vector() -> None:
    calldata = encode_execute_calldata(authorization(), SIGNATURE)

    assert calldata[:4].hex() == "9472102f"
    assert len(calldata) == 484
    assert calldata[4 + (9 * 32) : 4 + (10 * 32)].hex() == "00" * 12 + "55" * 20
    assert calldata[4 + (10 * 32) : 4 + (11 * 32)].hex() == "00" * 30 + "0160"

def test_execute_calldata_uses_the_ten_field_tuple() -> None:
    calldata = encode_execute_calldata(authorization(relayer=RELAYER), SIGNATURE)

    expected_head = (
        (CAPABILITY.hex(), RESERVATION.hex())
        + (
            "00" * 12 + OWNER[2:],
            "00" * 12 + PAYEE[2:],
            "00" * 12 + BASE_USDC.lower()[2:],
        )
        + (
            f"{1_250_000:064x}",
            f"{7:064x}",
            f"{1_700_000_000:064x}",
            f"{3:064x}",
            "00" * 12 + RELAYER[2:],
            f"{11 * 32:064x}",
        )
    )
    assert calldata[:4].hex() == "9472102f"
    assert len(calldata) == 484
    for index, expected in enumerate(expected_head):
        start = 4 + index * 32
        assert calldata[start : start + 32].hex() == expected
    assert calldata[4 + 11 * 32 : 4 + 12 * 32].hex() == f"{65:064x}"
    assert calldata[4 + 12 * 32 : 4 + 12 * 32 + 65] == SIGNATURE

def test_eip1559_unsigned_and_signed_vectors_are_deterministic() -> None:
    transaction = EIP1559Transaction(
        nonce=9,
        max_priority_fee_per_gas=1_000_000_000,
        max_fee_per_gas=2_000_000_000,
        gas_limit=250_000,
        to=EXECUTOR,
        data=encode_execute_calldata(authorization(), SIGNATURE),
    )

    unsigned = transaction.unsigned_bytes()
    assert unsigned[:48].hex() == (
        "02f9021082210509843b9aca0084773594008303d09094111111111111111111111111111111111111111180b901e494"
    )
    assert len(unsigned) == 532
    assert transaction.signing_hash().hex() == (
        "7643af9a87101d8d0300b72c006225851d41f9dbcad05a4fe7c279e3b6e28aa5"
    )

    signed = transaction.signed_bytes(
        (1).to_bytes(32, "big") + (2).to_bytes(32, "big") + bytes([27])
    )
    assert signed.hex().endswith("c0800102")
    assert raw_transaction_hash(signed).hex() == (
        "2e0288888ba5a24ab4db5042a163ee1d33806c891599892091f860b16425376a"
    )
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("chain_id", 1),
        ("to", "0x0000000000000000000000000000000000000000"),
        ("value", 1),
        ("max_fee_per_gas", 1),
    ],
)
def test_eip1559_rejects_unsafe_transaction_fields(field: str, value: object) -> None:
    values: dict[str, object] = {
        "nonce": 1,
        "max_priority_fee_per_gas": 2,
        "max_fee_per_gas": 3,
        "gas_limit": 21_000,
        "to": EXECUTOR,
        "data": b"",
    }
    values[field] = value

    with pytest.raises(EvmEncodingError):
        EIP1559Transaction(**values)


@pytest.mark.parametrize(
    "chain_id",
    [BASE_CHAIN_ID, POLYGON_CHAIN_ID, BASE_SEPOLIA_CHAIN_ID, POLYGON_AMOY_CHAIN_ID],
)
def test_eip1559_accepts_each_approved_chain(chain_id: int) -> None:
    transaction = EIP1559Transaction(
        nonce=1,
        max_priority_fee_per_gas=1,
        max_fee_per_gas=2,
        gas_limit=21_000,
        to=EXECUTOR,
        data=b"",
        chain_id=chain_id,
    )

    assert transaction.chain_id == chain_id


def test_execution_rejects_noncanonical_token_and_signature() -> None:
    with pytest.raises(EvmEncodingError):
        authorization(token="0x2222222222222222222222222222222222222222")
    with pytest.raises(EvmEncodingError):
        encode_execute_calldata(authorization(), bytes(64) + bytes([0]))
