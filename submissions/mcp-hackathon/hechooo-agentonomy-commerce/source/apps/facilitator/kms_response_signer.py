"""AWS KMS P-256 signer for Hosted response JWS values."""

from __future__ import annotations

import base64
import hashlib
from typing import Any

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, utils
from cryptography.hazmat.primitives.asymmetric.utils import (
    decode_dss_signature,
    encode_dss_signature,
)

from shared.hosted_facilitator_protocol import (
    HostedExecutionResponse,
    HostedPreflightResponse,
    _jwk_thumbprint,
    _public_jwk,
    canonical_json_bytes,
)


KMS_KEY_SPEC = "ECC_NIST_P256"
KMS_KEY_USAGE = "SIGN_VERIFY"
KMS_SIGNING_ALGORITHM = "ECDSA_SHA_256"
KMS_MESSAGE_TYPE = "DIGEST"
P256_ORDER = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551
_MAX_KMS_KEY_ID_LENGTH = 2048
_MAX_DER_SIGNATURE_LENGTH = 256


class KMSResponseSignerError(RuntimeError):
    """A bounded, provider-payload-free response signing failure."""


def _base64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _valid_kms_key_id(value: object) -> bool:
    if not isinstance(value, str) or not value or len(value) > _MAX_KMS_KEY_ID_LENGTH:
        return False
    return all(ord(character) >= 0x20 and ord(character) != 0x7F for character in value)


class KMSResponseSigner:
    """Sign Hosted responses with an AWS KMS ECC_NIST_P256 key.

    KMS is the only holder of the private key.  The validated public key is
    retained solely for JWK publication and signature verification.
    """

    __slots__ = ("_client", "_kms_key_id", "_public_key", "_public_jwk", "_key_id")

    def __init__(self, client: Any, *, key_id: str) -> None:
        if not _valid_kms_key_id(key_id):
            raise KMSResponseSignerError("KMS key ID is invalid")
        self._client = client
        self._kms_key_id = key_id

        try:
            metadata = client.get_public_key(KeyId=key_id)
        except Exception:
            raise KMSResponseSignerError("KMS public-key lookup failed") from None
        if not isinstance(metadata, dict):
            raise KMSResponseSignerError("KMS public-key response is invalid")
        if (
            metadata.get("KeySpec") != KMS_KEY_SPEC
            or metadata.get("KeyUsage") != KMS_KEY_USAGE
        ):
            raise KMSResponseSignerError("KMS key configuration is invalid")

        der = metadata.get("PublicKey")
        if not isinstance(der, (bytes, bytearray, memoryview)):
            raise KMSResponseSignerError("KMS public-key response is invalid")
        try:
            public_key = serialization.load_der_public_key(bytes(der))
        except (TypeError, ValueError):
            raise KMSResponseSignerError("KMS public key is invalid") from None
        if not isinstance(public_key, ec.EllipticCurvePublicKey) or not isinstance(
            public_key.curve, ec.SECP256R1
        ):
            raise KMSResponseSignerError("KMS public key is not P-256")
        try:
            public_jwk = _public_jwk(public_key)
            key_id_thumbprint = _jwk_thumbprint(public_jwk)
        except (TypeError, ValueError):
            raise KMSResponseSignerError("KMS public key is invalid") from None

        self._public_key = public_key
        self._public_jwk = public_jwk
        self._key_id = key_id_thumbprint

    @property
    def public_jwk(self) -> dict[str, str]:
        return dict(self._public_jwk)

    @property
    def key_id(self) -> str:
        return self._key_id

    def __repr__(self) -> str:
        return "KMSResponseSigner()"

    def sign(self, response: HostedPreflightResponse) -> str:
        if not isinstance(response, HostedPreflightResponse):
            raise KMSResponseSignerError("preflight response is invalid")
        return self._sign_response(response, typ="clink-response+jwt")

    def sign_execution(self, response: HostedExecutionResponse) -> str:
        if not isinstance(response, HostedExecutionResponse):
            raise KMSResponseSignerError("execution response is invalid")
        return self._sign_response(response, typ="clink-execution-response+jwt")

    def _sign_response(
        self,
        response: HostedPreflightResponse | HostedExecutionResponse,
        *,
        typ: str,
    ) -> str:
        if response.server_key_id != self.key_id:
            raise KMSResponseSignerError("response server key ID does not match")

        protected = canonical_json_bytes(
            {"alg": "ES256", "typ": typ, "kid": self.key_id}
        )
        payload = canonical_json_bytes(response.model_dump(mode="json"))
        protected_segment = _base64url_encode(protected)
        payload_segment = _base64url_encode(payload)
        signing_input = f"{protected_segment}.{payload_segment}".encode("ascii")
        digest = hashlib.sha256(signing_input).digest()

        try:
            result = self._client.sign(
                KeyId=self._kms_key_id,
                Message=digest,
                MessageType=KMS_MESSAGE_TYPE,
                SigningAlgorithm=KMS_SIGNING_ALGORITHM,
            )
        except Exception:
            raise KMSResponseSignerError("KMS signing request failed") from None
        if not isinstance(result, dict):
            raise KMSResponseSignerError("KMS signature response is invalid")
        der_signature = result.get("Signature")
        if not isinstance(der_signature, (bytes, bytearray, memoryview)):
            raise KMSResponseSignerError("KMS signature response is invalid")
        der_bytes = bytes(der_signature)
        if not der_bytes or len(der_bytes) > _MAX_DER_SIGNATURE_LENGTH:
            raise KMSResponseSignerError("KMS signature encoding is invalid")
        try:
            r, s = decode_dss_signature(der_bytes)
            if encode_dss_signature(r, s) != der_bytes:
                raise ValueError("non-canonical DER")
        except (TypeError, ValueError):
            raise KMSResponseSignerError("KMS signature encoding is invalid") from None
        if r <= 0 or r >= P256_ORDER or s <= 0 or s >= P256_ORDER:
            raise KMSResponseSignerError("KMS signature scalar is invalid")
        try:
            self._public_key.verify(
                der_bytes,
                digest,
                ec.ECDSA(utils.Prehashed(hashes.SHA256())),
            )
        except Exception:
            raise KMSResponseSignerError("KMS signature does not match public key") from None

        jose_signature = r.to_bytes(32, "big") + s.to_bytes(32, "big")
        return f"{protected_segment}.{payload_segment}.{_base64url_encode(jose_signature)}"
