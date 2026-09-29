from __future__ import annotations

import base64
import hashlib

import jwt
import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, utils
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

from kms_response_signer import KMSResponseSigner, KMSResponseSignerError
from shared.hosted_facilitator_protocol import (
    HOSTED_PROTOCOL_VERSION,
    HostedExecutionResponse,
    HostedPaymentEnvelope,
    HostedPreflightResponse,
    _jwk_thumbprint,
    _public_jwk,
    canonical_json_bytes,
    verify_execution_response,
    verify_preflight_response,
)
from shared.payment_capability import PAYMENT_CAPABILITY_VERSION


KMS_KEY_ID = "arn:aws:kms:us-east-1:123456789012:key/response"
BASE_USDC = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"
P256_ORDER = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551


class FakeKMS:
    def __init__(
        self,
        *,
        private_key: ec.EllipticCurvePrivateKey | None = None,
        public_key: ec.EllipticCurvePrivateKey | None = None,
        key_spec: str = "ECC_NIST_P256",
        key_usage: str = "SIGN_VERIFY",
        signature: bytes | None = None,
        public_error: Exception | None = None,
        sign_error: Exception | None = None,
    ) -> None:
        self.private_key = private_key or ec.generate_private_key(ec.SECP256R1())
        self.public_key = public_key or self.private_key
        self.key_spec = key_spec
        self.key_usage = key_usage
        self.signature = signature
        self.public_error = public_error
        self.sign_error = sign_error
        self.public_key_calls: list[dict[str, object]] = []
        self.sign_calls: list[dict[str, object]] = []

    def get_public_key(self, **kwargs: object) -> dict[str, object]:
        self.public_key_calls.append(kwargs)
        if self.public_error is not None:
            raise self.public_error
        public_der = self.public_key.public_key().public_bytes(
            serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        return {
            "KeySpec": self.key_spec,
            "KeyUsage": self.key_usage,
            "PublicKey": public_der,
        }

    def sign(self, **kwargs: object) -> dict[str, object]:
        self.sign_calls.append(kwargs)
        if self.sign_error is not None:
            raise self.sign_error
        if self.signature is not None:
            return {"Signature": self.signature}
        digest = kwargs["Message"]
        assert isinstance(digest, bytes)
        signature = self.private_key.sign(
            digest,
            ec.ECDSA(utils.Prehashed(hashes.SHA256())),
        )
        return {"Signature": signature}


def preflight_envelope(**overrides: object) -> HostedPaymentEnvelope:
    values: dict[str, object] = {
        "protocol_version": HOSTED_PROTOCOL_VERSION,
        "audience": "hosted-facilitator",
        "http_method": "POST",
        "http_path": "/v1/preflight",
        "request_id": "request_1",
        "idempotency_key": "idempotency_1",
        "tenant_id": "tenant_1",
        "node_id": "node_1",
        "wallet_binding_id": "wallet_binding_1",
        "payment_capability_version": PAYMENT_CAPABILITY_VERSION,
        "payment_capability_id": "capability_1",
        "payment_capability_hash": "0x" + "08" * 32,
        "wallet_identity_id": "wallet_identity_1",
        "wallet_address": "0x" + "11" * 20,
        "spending_grant_id": "grant_1",
        "spending_grant_hash": "0x" + "a1" * 32,
        "asset_allowance_id": "allowance_1",
        "reservation_id": "reservation_1",
        "reservation_hash": "0x" + "18" * 32,
        "action_id": "action_1",
        "policy_decision_id": "decision_1",
        "policy_snapshot_hash": "0x" + "b2" * 32,
        "risk_evidence_hash": "0x" + "c3" * 32,
        "purchase_id": "purchase_1",
        "merchant_id": "merchant_1",
        "quote_hash": "0x" + "d4" * 32,
        "payment_challenge_hash": "0x" + "e5" * 32,
        "chain_id": "eip155:8453",
        "asset_contract": BASE_USDC,
        "amount_atomic": "1000000",
        "pay_to": "0x" + "33" * 20,
        "executor_contract": "0x" + "44" * 20,
        "execution_scope_hash": "0x" + "f6" * 32,
        "request_nonce": "0x" + "07" * 32,
        "issued_at": 100,
        "expires_at": 160,
    }
    values.update(overrides)
    return HostedPaymentEnvelope(**values)


def execution_envelope(**overrides: object) -> HostedPaymentEnvelope:
    values = preflight_envelope(http_path="/v1/executions").model_dump()
    values.update(overrides)
    return HostedPaymentEnvelope(**values)


def preflight_response(
    signer: KMSResponseSigner,
    envelope: HostedPaymentEnvelope,
    **overrides: object,
) -> HostedPreflightResponse:
    values: dict[str, object] = {
        "provider_request_id": "provider_1",
        "request_id": envelope.request_id,
        "request_hash": envelope.request_hash,
        "idempotency_key": envelope.idempotency_key,
        "state": "dry_run_accepted",
        "chain_id": envelope.chain_id,
        "asset_contract": envelope.asset_contract,
        "amount_atomic": envelope.amount_atomic,
        "pay_to": envelope.pay_to,
        "transaction_hash": None,
        "submitted_at": None,
        "confirmed_at": None,
        "server_key_id": signer.key_id,
    }
    values.update(overrides)
    return HostedPreflightResponse(**values)


def execution_response(
    signer: KMSResponseSigner,
    envelope: HostedPaymentEnvelope,
    **overrides: object,
) -> HostedExecutionResponse:
    values: dict[str, object] = {
        "protocol_version": HOSTED_PROTOCOL_VERSION,
        "http_path": "/v1/executions",
        "audience": "hosted-facilitator",
        "issuer": "hosted-facilitator",
        "chain_id": "eip155:8453",
        "request_id": envelope.request_id,
        "request_hash": envelope.request_hash,
        "idempotency_key": envelope.idempotency_key,
        "execution_id": "execution_1",
        "capability_id": envelope.payment_capability_id,
        "capability_hash": envelope.payment_capability_hash,
        "reservation_id": envelope.reservation_id,
        "reservation_hash": envelope.reservation_hash,
        "purchase_id": envelope.purchase_id,
        "execution_scope_hash": envelope.execution_scope_hash,
        "owner": envelope.wallet_address,
        "payee": envelope.pay_to,
        "token": envelope.asset_contract,
        "amount_atomic": envelope.amount_atomic,
        "executor": envelope.executor_contract,
        "signer_epoch": 1,
        "owner_nonce": envelope.request_nonce,
        "deadline": envelope.expires_at,
        "state": "submitted",
        "transaction_hash": "0x" + "aa" * 32,
        "receipt_block_hash": None,
        "receipt_block_number": None,
        "safe_block_hash": None,
        "safe_block_number": None,
        "confirmations": 0,
        "failure_reason_code": None,
        "issued_at": envelope.issued_at + 1,
        "submitted_at": envelope.issued_at + 2,
        "confirmed_at": None,
        "finalized_at": None,
        "reverted_at": None,
        "reorg_reviewed_at": None,
        "released_at": None,
        "expired_at": None,
        "watcher_version": "hosted-base-watcher-v1",
        "server_key_id": signer.key_id,
    }
    values.update(overrides)
    return HostedExecutionResponse(**values)


def signer(client: FakeKMS) -> KMSResponseSigner:
    return KMSResponseSigner(client, key_id=KMS_KEY_ID)


def b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def test_constructor_validates_p256_jwk_thumbprint_and_exact_kms_lookup() -> None:
    client = FakeKMS()
    created = signer(client)

    expected_public_key = client.private_key.public_key()
    expected_jwk = _public_jwk(expected_public_key)
    assert created.public_jwk == expected_jwk
    assert created.key_id == _jwk_thumbprint(expected_jwk)
    assert client.public_key_calls == [{"KeyId": KMS_KEY_ID}]
    assert KMS_KEY_ID not in repr(created)


def test_preflight_sign_uses_exact_digest_and_existing_verifier() -> None:
    client = FakeKMS()
    created = signer(client)
    envelope = preflight_envelope()
    response = preflight_response(created, envelope)

    token = created.sign(response)
    header, payload, _signature = token.split(".")
    assert jwt.get_unverified_header(token) == {
        "alg": "ES256",
        "typ": "clink-response+jwt",
        "kid": created.key_id,
    }
    assert verify_preflight_response(token, created.public_jwk, envelope) == response

    signing_input = f"{header}.{payload}".encode("ascii")
    assert client.sign_calls == [
        {
            "KeyId": KMS_KEY_ID,
            "Message": hashlib.sha256(signing_input).digest(),
            "MessageType": "DIGEST",
            "SigningAlgorithm": "ECDSA_SHA_256",
        }
    ]
    assert payload == b64url(canonical_json_bytes(response.model_dump(mode="json")))


def test_execution_sign_uses_execution_type_and_existing_verifier() -> None:
    client = FakeKMS()
    created = signer(client)
    envelope = execution_envelope()
    response = execution_response(created, envelope)

    token = created.sign_execution(response)

    assert jwt.get_unverified_header(token) == {
        "alg": "ES256",
        "typ": "clink-execution-response+jwt",
        "kid": created.key_id,
    }
    assert (
        verify_execution_response(
            token,
            created.public_jwk,
            envelope,
            now=103,
            expected_execution_id=response.execution_id,
        )
        == response
    )


@pytest.mark.parametrize(
    ("key_spec", "key_usage"),
    [("ECC_SECG_P256K1", "SIGN_VERIFY"), ("ECC_NIST_P256", "ENCRYPT_DECRYPT")],
)
def test_constructor_rejects_wrong_kms_metadata(key_spec: str, key_usage: str) -> None:
    with pytest.raises(KMSResponseSignerError, match="KMS key configuration"):
        signer(FakeKMS(key_spec=key_spec, key_usage=key_usage))


def test_constructor_rejects_wrong_curve_and_malformed_der() -> None:
    wrong_curve = ec.generate_private_key(ec.SECP384R1())
    with pytest.raises(KMSResponseSignerError, match="P-256"):
        signer(FakeKMS(public_key=wrong_curve))

    malformed = FakeKMS()
    malformed.public_key_calls.clear()
    malformed.get_public_key = lambda **kwargs: {
        "KeySpec": "ECC_NIST_P256",
        "KeyUsage": "SIGN_VERIFY",
        "PublicKey": b"not-a-der-key",
    }
    with pytest.raises(KMSResponseSignerError, match="public key"):
        signer(malformed)


def test_signature_der_and_scalar_validation_is_strict() -> None:
    client = FakeKMS(signature=b"not-der")
    created = signer(client)
    envelope = preflight_envelope()
    response = preflight_response(created, envelope)
    with pytest.raises(KMSResponseSignerError, match="signature encoding"):
        created.sign(response)

    for scalar in (0, P256_ORDER):
        client = FakeKMS(signature=encode_dss_signature(scalar, 1))
        created = signer(client)
        response = preflight_response(created, envelope)
        with pytest.raises(KMSResponseSignerError, match="signature scalar"):
            created.sign(response)


def test_server_key_mismatch_fails_before_kms_sign() -> None:
    client = FakeKMS()
    created = signer(client)
    envelope = preflight_envelope()
    response = preflight_response(created, envelope, server_key_id="different-key")

    with pytest.raises(KMSResponseSignerError, match="key ID"):
        created.sign(response)
    assert client.sign_calls == []


def test_provider_errors_are_bounded_and_secret_free() -> None:
    secret = "provider-secret-payload"
    with pytest.raises(KMSResponseSignerError) as public_error:
        signer(FakeKMS(public_error=RuntimeError(secret)))
    assert secret not in str(public_error.value)

    client = FakeKMS(sign_error=RuntimeError(secret))
    created = signer(client)
    response = preflight_response(created, preflight_envelope())
    with pytest.raises(KMSResponseSignerError) as sign_error:
        created.sign(response)
    assert secret not in str(sign_error.value)
