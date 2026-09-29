"""Deterministic Agentonomy Executor EIP-712, ABI and EIP-1559 encoders."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import rlp
from eth_abi import encode as abi_encode
from eth_utils import keccak


BASE_CHAIN_ID = 8453
BASE_USDC = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
BASE_USDC_ADDRESS = BASE_USDC
POLYGON_CHAIN_ID = 137
POLYGON_USDC = "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359"
BASE_SEPOLIA_CHAIN_ID = 84532
BASE_SEPOLIA_USDC = "0x036CbD53842c5426634e7929541eC2318f3dCF7e"
POLYGON_AMOY_CHAIN_ID = 80002
POLYGON_AMOY_USDC = "0x41E94Eb019C0762f9Bfcf9Fb1E58725BfB0e7582"
USDC_BY_CHAIN_ID = {
    BASE_CHAIN_ID: BASE_USDC,
    POLYGON_CHAIN_ID: POLYGON_USDC,
    BASE_SEPOLIA_CHAIN_ID: BASE_SEPOLIA_USDC,
    POLYGON_AMOY_CHAIN_ID: POLYGON_AMOY_USDC,
}
SUPPORTED_CHAIN_IDS = frozenset(USDC_BY_CHAIN_ID)
EXECUTOR_EIP712_NAME = "Agentonomy USDC Executor"
EXECUTOR_EIP712_VERSION = "1"
EIP712_DOMAIN_TYPE = "EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)"
EXECUTION_TYPE = (
    "Execution(bytes32 capabilityHash,bytes32 reservationHash,address owner,address payee,address token,"
    "uint256 amount,uint256 nonce,uint256 deadline,uint256 signerEpoch,address relayer)"
)
EXECUTE_FUNCTION_TYPE = "execute((bytes32,bytes32,address,address,address,uint256,uint256,uint256,uint256,address),bytes)"
EXECUTE_SELECTOR = keccak(text=EXECUTE_FUNCTION_TYPE)[:4]

UINT256_MAX = 2**256 - 1
SECP256K1_N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
SECP256K1_HALF_N = 0x7FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF5D576E7357A4501DDFE92F46681B20A0


class EvmEncodingError(ValueError):
    """Raised when an authorization or transaction cannot be encoded safely."""


def _bytes(value: object, *, field: str) -> bytes:
    if isinstance(value, bytes):
        return value
    if isinstance(value, (bytearray, memoryview)):
        return bytes(value)
    if isinstance(value, str) and value.startswith("0x"):
        try:
            return bytes.fromhex(value[2:])
        except ValueError as exc:
            raise EvmEncodingError(f"{field} is not valid hex") from exc
    raise EvmEncodingError(f"{field} must be bytes or 0x-prefixed hex")


def _bytes32(value: object, *, field: str) -> bytes:
    result = _bytes(value, field=field)
    if len(result) != 32:
        raise EvmEncodingError(f"{field} must be exactly 32 bytes")
    return result


def _address(value: object, *, field: str) -> str:
    if not isinstance(value, str) or len(value) != 42 or not value.startswith("0x"):
        raise EvmEncodingError(f"{field} must be a 20-byte 0x address")
    try:
        raw = bytes.fromhex(value[2:])
    except ValueError as exc:
        raise EvmEncodingError(f"{field} must be a 20-byte 0x address") from exc
    if len(raw) != 20 or raw == bytes(20):
        raise EvmEncodingError(f"{field} must be a nonzero 20-byte address")
    return "0x" + raw.hex()


def _uint(value: object, *, field: str, positive: bool = False) -> int:
    if type(value) is not int or value < 0 or value > UINT256_MAX:
        raise EvmEncodingError(f"{field} must be a uint256")
    if positive and value == 0:
        raise EvmEncodingError(f"{field} must be positive")
    return value


def _approved_chain(value: object, *, field: str = "chain_id") -> int:
    chain_id = _uint(value, field=field)
    if chain_id not in SUPPORTED_CHAIN_IDS:
        raise EvmEncodingError(f"{field} is not an approved execution chain")
    return chain_id


def _normalise_signature(value: object, *, execution: bool) -> tuple[int, int, int]:
    signature = _bytes(value, field="signature")
    if len(signature) != 65:
        raise EvmEncodingError("signature must be exactly 65 bytes")
    r = int.from_bytes(signature[:32], "big")
    s = int.from_bytes(signature[32:64], "big")
    v = signature[64]
    allowed_v = (27, 28) if execution else (0, 1, 27, 28)
    if v not in allowed_v:
        raise EvmEncodingError("signature recovery id is invalid")
    if r == 0 or r >= SECP256K1_N or s == 0 or s > SECP256K1_HALF_N:
        raise EvmEncodingError("signature scalar is invalid")
    return v, r, s


@dataclass(frozen=True)
class ExecutionAuthorization:
    capability_hash: bytes | str
    reservation_hash: bytes | str
    owner: str
    payee: str
    token: str
    amount: int
    nonce: int
    deadline: int
    signer_epoch: int
    relayer: str
    chain_id: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "capability_hash", _bytes32(self.capability_hash, field="capability_hash"))
        object.__setattr__(self, "reservation_hash", _bytes32(self.reservation_hash, field="reservation_hash"))
        if self.capability_hash == bytes(32):
            raise EvmEncodingError("capability_hash must be nonzero")
        if self.reservation_hash == bytes(32):
            raise EvmEncodingError("reservation_hash must be nonzero")
        object.__setattr__(self, "owner", _address(self.owner, field="owner"))
        object.__setattr__(self, "payee", _address(self.payee, field="payee"))
        object.__setattr__(self, "relayer", _address(self.relayer, field="relayer"))
        token = _address(self.token, field="token")
        if self.chain_id is None:
            matching_chain_ids = [
                chain_id
                for chain_id, chain_token in USDC_BY_CHAIN_ID.items()
                if token.lower() == chain_token.lower()
            ]
            if len(matching_chain_ids) != 1:
                raise EvmEncodingError("token is not an approved USDC contract")
            chain_id = matching_chain_ids[0]
        else:
            chain_id = _approved_chain(self.chain_id)
        object.__setattr__(self, "chain_id", chain_id)
        expected_token = USDC_BY_CHAIN_ID[chain_id]
        if token.lower() != expected_token.lower():
            raise EvmEncodingError("token must be canonical USDC for chain")
        object.__setattr__(self, "token", token)
        object.__setattr__(self, "amount", _uint(self.amount, field="amount", positive=True))
        object.__setattr__(self, "nonce", _uint(self.nonce, field="nonce"))
        object.__setattr__(self, "deadline", _uint(self.deadline, field="deadline"))
        object.__setattr__(self, "signer_epoch", _uint(self.signer_epoch, field="signer_epoch", positive=True))

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ExecutionAuthorization":
        try:
            return cls(**value)
        except TypeError as exc:
            raise EvmEncodingError("execution fields are invalid") from exc


def _execution(value: ExecutionAuthorization | Mapping[str, Any]) -> ExecutionAuthorization:
    if isinstance(value, ExecutionAuthorization):
        return value
    if isinstance(value, Mapping):
        return ExecutionAuthorization.from_mapping(value)
    raise EvmEncodingError("execution must be an ExecutionAuthorization")


def _execution_values(execution: ExecutionAuthorization) -> list[object]:
    return [
        execution.capability_hash,
        execution.reservation_hash,
        execution.owner,
        execution.payee,
        execution.token,
        execution.amount,
        execution.nonce,
        execution.deadline,
        execution.signer_epoch,
        execution.relayer,
    ]


def domain_separator(executor_address: str, chain_id: int = BASE_CHAIN_ID) -> bytes:
    executor = _address(executor_address, field="executor_address")
    chain_id = _approved_chain(chain_id)
    return keccak(
        abi_encode(
            ["bytes32", "bytes32", "bytes32", "uint256", "address"],
            [
                keccak(text=EIP712_DOMAIN_TYPE),
                keccak(text=EXECUTOR_EIP712_NAME),
                keccak(text=EXECUTOR_EIP712_VERSION),
                chain_id,
                executor,
            ],
        )
    )


def hash_execution(
    execution: ExecutionAuthorization | Mapping[str, Any],
    executor_address: str,
    chain_id: int | None = None,
) -> bytes:
    value = _execution(execution)
    selected_chain_id = value.chain_id if chain_id is None else _approved_chain(chain_id)
    if selected_chain_id != value.chain_id:
        raise EvmEncodingError("chain_id does not match execution")
    struct_hash = keccak(
        abi_encode(
            [
                "bytes32",
                "bytes32",
                "bytes32",
                "address",
                "address",
                "address",
                "uint256",
                "uint256",
                "uint256",
                "uint256",
                "address",
            ],
            [keccak(text=EXECUTION_TYPE), *_execution_values(value)],
        )
    )
    return keccak(b"\x19\x01" + domain_separator(executor_address, selected_chain_id) + struct_hash)


def encode_execute_calldata(
    execution: ExecutionAuthorization | Mapping[str, Any], signature: bytes | str
) -> bytes:
    value = _execution(execution)
    _normalise_signature(signature, execution=True)
    signature_bytes = _bytes(signature, field="signature")
    encoded = abi_encode(
        ["(bytes32,bytes32,address,address,address,uint256,uint256,uint256,uint256,address)", "bytes"],
        [_execution_values(value), signature_bytes],
    )
    return EXECUTE_SELECTOR + encoded


def _normalise_access_list(value: object) -> tuple[tuple[str, tuple[bytes, ...]], ...]:
    if value is None:
        return ()
    if isinstance(value, (str, bytes, bytearray, memoryview)) or not isinstance(value, Sequence):
        raise EvmEncodingError("access_list must be a sequence")
    result: list[tuple[str, tuple[bytes, ...]]] = []
    for entry in value:
        if not isinstance(entry, Sequence) or len(entry) != 2:
            raise EvmEncodingError("access_list entries are invalid")
        address = _address(entry[0], field="access_list address")
        keys_value = entry[1]
        if isinstance(keys_value, (str, bytes, bytearray, memoryview)) or not isinstance(keys_value, Sequence):
            raise EvmEncodingError("access_list storage keys are invalid")
        keys = tuple(_bytes32(key, field="access_list storage key") for key in keys_value)
        result.append((address, keys))
    return tuple(result)


def _access_list_rlp(access_list: tuple[tuple[str, tuple[bytes, ...]], ...]) -> list[list[object]]:
    return [[bytes.fromhex(address[2:]), list(keys)] for address, keys in access_list]


def _uint_bytes(value: int) -> bytes:
    return b"" if value == 0 else value.to_bytes((value.bit_length() + 7) // 8, "big")


@dataclass(frozen=True)
class EIP1559Transaction:
    nonce: int
    max_priority_fee_per_gas: int
    max_fee_per_gas: int
    gas_limit: int
    to: str
    data: bytes | str
    value: int = 0
    access_list: Sequence[object] = ()
    chain_id: int = BASE_CHAIN_ID

    def __post_init__(self) -> None:
        object.__setattr__(self, "chain_id", _approved_chain(self.chain_id))
        object.__setattr__(self, "nonce", _uint(self.nonce, field="nonce"))
        object.__setattr__(
            self,
            "max_priority_fee_per_gas",
            _uint(self.max_priority_fee_per_gas, field="max_priority_fee_per_gas"),
        )
        object.__setattr__(self, "max_fee_per_gas", _uint(self.max_fee_per_gas, field="max_fee_per_gas", positive=True))
        if self.max_fee_per_gas < self.max_priority_fee_per_gas:
            raise EvmEncodingError("max_fee_per_gas must cover max_priority_fee_per_gas")
        object.__setattr__(self, "gas_limit", _uint(self.gas_limit, field="gas_limit", positive=True))
        object.__setattr__(self, "to", _address(self.to, field="to"))
        object.__setattr__(self, "value", _uint(self.value, field="value"))
        if self.value != 0:
            raise EvmEncodingError("executor transaction value must be zero")
        object.__setattr__(self, "data", _bytes(self.data, field="data"))
        object.__setattr__(self, "access_list", _normalise_access_list(self.access_list))

    def _unsigned_fields(self) -> list[object]:
        return [
            _uint_bytes(self.chain_id),
            _uint_bytes(self.nonce),
            _uint_bytes(self.max_priority_fee_per_gas),
            _uint_bytes(self.max_fee_per_gas),
            _uint_bytes(self.gas_limit),
            bytes.fromhex(self.to[2:]),
            _uint_bytes(self.value),
            self.data,
            _access_list_rlp(self.access_list),
        ]

    def unsigned_bytes(self) -> bytes:
        return b"\x02" + rlp.encode(self._unsigned_fields())

    def signing_hash(self) -> bytes:
        return keccak(self.unsigned_bytes())

    def signed_bytes(self, signature: bytes | str) -> bytes:
        v, r, s = _normalise_signature(signature, execution=False)
        y_parity = v - 27 if v in (27, 28) else v
        return b"\x02" + rlp.encode(self._unsigned_fields() + [_uint_bytes(y_parity), _uint_bytes(r), _uint_bytes(s)])


def encode_eip1559_unsigned(transaction: EIP1559Transaction) -> bytes:
    if not isinstance(transaction, EIP1559Transaction):
        raise EvmEncodingError("transaction must be an EIP1559Transaction")
    return transaction.unsigned_bytes()


def encode_eip1559_signed(transaction: EIP1559Transaction, signature: bytes | str) -> bytes:
    if not isinstance(transaction, EIP1559Transaction):
        raise EvmEncodingError("transaction must be an EIP1559Transaction")
    return transaction.signed_bytes(signature)


def eip1559_signing_hash(transaction: EIP1559Transaction) -> bytes:
    if not isinstance(transaction, EIP1559Transaction):
        raise EvmEncodingError("transaction must be an EIP1559Transaction")
    return transaction.signing_hash()


def raw_transaction_hash(raw_transaction: bytes | str) -> bytes:
    raw = _bytes(raw_transaction, field="raw_transaction")
    if not raw or raw[0] != 0x02:
        raise EvmEncodingError("raw transaction must be an EIP-1559 transaction")
    return keccak(raw)


build_execute_calldata = encode_execute_calldata
