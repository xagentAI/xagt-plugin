"""AWS KMS secp256k1 execution-authority signing adapter."""

from __future__ import annotations

from typing import Any

from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.serialization import load_der_public_key
from eth_keys import keys
from eth_utils import keccak

from evm import SECP256K1_HALF_N, SECP256K1_N


KMS_KEY_SPEC = "ECC_SECG_P256K1"
KMS_KEY_USAGE = "SIGN_VERIFY"
KMS_SIGNING_ALGORITHM = "ECDSA_SHA_256"
KMS_MESSAGE_TYPE = "DIGEST"


class KMSConfigurationError(ValueError):
    """Raised when signing identities are not safely configured."""


class KMSSigningError(RuntimeError):
    """Raised when KMS cannot produce a verified execution signature."""


def _normalise_address(value: object, *, field: str) -> str:
    if not isinstance(value, str) or len(value) != 42 or not value.startswith("0x"):
        raise KMSConfigurationError(f"{field} must be a 20-byte 0x address")
    try:
        raw = bytes.fromhex(value[2:])
    except ValueError as exc:
        raise KMSConfigurationError(f"{field} must be a 20-byte 0x address") from exc
    if len(raw) != 20 or raw == bytes(20):
        raise KMSConfigurationError(f"{field} must be a nonzero 20-byte address")
    return "0x" + raw.hex()


def _public_key_bytes(public_key: ec.EllipticCurvePublicKey) -> bytes:
    numbers = public_key.public_numbers()
    return b"\x04" + numbers.x.to_bytes(32, "big") + numbers.y.to_bytes(32, "big")


def _ethereum_address(public_key_bytes: bytes) -> str:
    if len(public_key_bytes) != 65 or public_key_bytes[0] != 4:
        raise KMSSigningError("KMS public key encoding is invalid")
    return "0x" + keccak(public_key_bytes[1:])[-20:].hex()


class KMSExecutionSigner:
    """Sign EVM digests with an AWS KMS ECC_SECG_P256K1 key.

    The adapter never accepts or stores private key material. Every signature
    is checked against the KMS public key before a compact 65-byte result is
    returned.
    """

    def __init__(
        self,
        client: Any,
        *,
        key_id: str,
        expected_signer_address: str,
        gas_relayer_key_id: str | None = None,
        gas_relayer_address: str | None = None,
    ) -> None:
        if not isinstance(key_id, str) or not key_id.strip():
            raise KMSConfigurationError("KMS key_id is required")
        if gas_relayer_key_id is not None and gas_relayer_key_id == key_id:
            raise KMSConfigurationError("execution and gas signer keys must differ")
        expected = _normalise_address(expected_signer_address, field="expected_signer_address")
        if gas_relayer_address is not None:
            relayer = _normalise_address(gas_relayer_address, field="gas_relayer_address")
            if relayer == expected:
                raise KMSConfigurationError("execution and gas signer addresses must differ")
        self._client = client
        self._key_id = key_id
        self._expected_signer_address = expected

    @property
    def key_id(self) -> str:
        return self._key_id

    @property
    def expected_signer_address(self) -> str:
        return self._expected_signer_address

    def __repr__(self) -> str:
        return (
            "KMSExecutionSigner(key_ref='<redacted>', "
            f"expected_signer_address={self._expected_signer_address!r})"
        )

    def validate(self) -> None:
        """Verify the configured KMS key identity without signing."""

        _public_key, public_address = self._load_public_key()
        if public_address != self._expected_signer_address:
            raise KMSSigningError("KMS signer address mismatch")

    def _load_public_key(self) -> tuple[bytes, str]:
        try:
            response = self._client.get_public_key(KeyId=self._key_id)
        except Exception as exc:
            raise KMSSigningError("KMS public-key lookup failed") from exc
        if not isinstance(response, dict):
            raise KMSSigningError("KMS public-key response is invalid")
        if response.get("KeySpec") != KMS_KEY_SPEC or response.get("KeyUsage") != KMS_KEY_USAGE:
            raise KMSSigningError("KMS key is not an ECDSA signing key")
        der = response.get("PublicKey")
        if not isinstance(der, (bytes, bytearray, memoryview)):
            raise KMSSigningError("KMS public-key response is invalid")
        try:
            loaded = load_der_public_key(bytes(der))
        except (TypeError, ValueError) as exc:
            raise KMSSigningError("KMS public key is invalid") from exc
        if not isinstance(loaded, ec.EllipticCurvePublicKey) or loaded.curve.name != "secp256k1":
            raise KMSSigningError("KMS public key is not secp256k1")
        public_key_bytes = _public_key_bytes(loaded)
        return public_key_bytes, _ethereum_address(public_key_bytes)

    def sign_digest(self, digest: bytes | bytearray | memoryview) -> bytes:
        if not isinstance(digest, (bytes, bytearray, memoryview)) or len(digest) != 32:
            raise KMSSigningError("digest must be exactly 32 bytes")
        digest_bytes = bytes(digest)
        public_key_bytes, public_address = self._load_public_key()
        if public_address != self._expected_signer_address:
            raise KMSSigningError("KMS signer address mismatch")
        try:
            response = self._client.sign(
                KeyId=self._key_id,
                Message=digest_bytes,
                MessageType=KMS_MESSAGE_TYPE,
                SigningAlgorithm=KMS_SIGNING_ALGORITHM,
            )
        except Exception as exc:
            raise KMSSigningError("KMS signing request failed") from exc
        if not isinstance(response, dict):
            raise KMSSigningError("KMS signature response is invalid")
        der_signature = response.get("Signature")
        if not isinstance(der_signature, (bytes, bytearray, memoryview)):
            raise KMSSigningError("KMS signature response is invalid")
        try:
            r, s = decode_dss_signature(bytes(der_signature))
        except (TypeError, ValueError) as exc:
            raise KMSSigningError("KMS signature encoding is invalid") from exc
        if r <= 0 or r >= SECP256K1_N or s <= 0 or s >= SECP256K1_N:
            raise KMSSigningError("KMS signature scalar is invalid")
        if s > SECP256K1_HALF_N:
            s = SECP256K1_N - s
        try:
            parity = self._recover_parity(digest_bytes, r, s, public_key_bytes)
        except Exception as exc:
            if isinstance(exc, KMSSigningError):
                raise
            raise KMSSigningError("KMS signature does not match signer") from exc
        return r.to_bytes(32, "big") + s.to_bytes(32, "big") + bytes([27 + parity])

    @staticmethod
    def _recover_parity(digest: bytes, r: int, s: int, public_key_bytes: bytes) -> int:
        for parity in (0, 1):
            try:
                recovered = keys.Signature(vrs=(parity, r, s)).recover_public_key_from_msg_hash(digest)
            except Exception:
                continue
            if recovered.to_bytes() == public_key_bytes[1:]:
                return parity
        raise KMSSigningError("KMS signature does not match signer")

    sign_execution_digest = sign_digest


AwsKmsExecutionSigner = KMSExecutionSigner
