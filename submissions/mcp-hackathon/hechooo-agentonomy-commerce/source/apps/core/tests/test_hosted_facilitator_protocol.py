from __future__ import annotations

import base64
import hashlib
import json
from decimal import Decimal

import jwt
import pytest
from cryptography.hazmat.primitives.serialization import load_der_private_key

from shared.hosted_facilitator_protocol import (
    HOSTED_BASE_USDC,
    HOSTED_POLYGON_USDC,
    HOSTED_PROTOCOL_VERSION,
    MAX_PAYMENT_VALIDITY_SECONDS,
    DPoPClaims,
    DeviceSigningKey,
    HostedExecutionResponse,
    HostedPaymentEnvelope,
    HostedPreflightResponse,
    HostedProtocolError,
    build_dpop_proof,
    canonical_json_bytes,
    sha256_identifier,
    sign_payment_envelope,
    sign_execution_response,
    sign_preflight_response,
    validate_payment_window,
    verify_dpop_proof,
    verify_payment_envelope,
    verify_execution_response,
    verify_preflight_response,
)
from shared.payment_capability import PAYMENT_CAPABILITY_VERSION


def valid_envelope(**overrides: object) -> HostedPaymentEnvelope:
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
        "asset_contract": HOSTED_BASE_USDC,
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


def base64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def noncanonical_base64url_alias(value: str) -> str:
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
    final_index = alphabet.index(value[-1])
    return value[:-1] + alphabet[(final_index & 0b111100) | 0b000001]


def compact_jws(header: dict[str, object], payload: bytes, signature: bytes = b"") -> str:
    return ".".join(
        (
            base64url(canonical_json_bytes(header)),
            base64url(payload),
            base64url(signature),
        )
    )


def replace_compact_jws_payload(token: str, field: str, replacement: object) -> str:
    header, payload, signature = token.split(".")
    decoded = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    decoded[field] = replacement
    return ".".join((header, base64url(canonical_json_bytes(decoded)), signature))


def resign_token(
    key: DeviceSigningKey,
    token: str,
    *,
    header_overrides: dict[str, object] | None = None,
    claim_overrides: dict[str, object] | None = None,
) -> str:
    header = jwt.get_unverified_header(token)
    claims = jwt.decode(token, options={"verify_signature": False})
    header.update(header_overrides or {})
    claims.update(claim_overrides or {})
    private_key = load_der_private_key(key.pkcs8_der, password=None)
    return jwt.encode(claims, private_key, algorithm="ES256", headers=header)


def test_envelope_hash_is_stable_for_the_same_scope():
    first = valid_envelope()
    second = HostedPaymentEnvelope(**dict(reversed(list(first.model_dump().items()))))

    assert first.canonical_bytes() == second.canonical_bytes()
    assert first.request_hash == second.request_hash
    assert first.request_hash == sha256_identifier(first.canonical_bytes())


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("payment_capability_version", "clink-payment-capability-v2"),
        ("payment_capability_id", "capability_2"),
        ("payment_capability_hash", "0x" + "09" * 32),
        ("reservation_hash", "0x" + "19" * 32),
    ],
)
def test_every_capability_binding_field_is_signed_into_request_hash(
    field, replacement
):
    envelope = valid_envelope()
    changed = envelope.model_copy(update={field: replacement})

    assert changed.request_hash != envelope.request_hash


def test_legacy_call_data_hash_is_rejected():
    values = valid_envelope().model_dump(mode="json")
    values["call_data_hash"] = "0x" + "99" * 32

    with pytest.raises(ValueError, match="call_data_hash"):
        HostedPaymentEnvelope(**values)


def test_canonical_json_bytes_are_deterministic_utf8_json():
    assert canonical_json_bytes({"z": "é", "a": 1}) == b'{"a":1,"z":"\xc3\xa9"}'


def test_canonical_json_bytes_matches_fixed_cross_language_vector():
    value = {
        "amount_atomic": 1000000,
        "enabled": True,
        "nested": {"b": ["x", 2, None], "a": "é"},
    }

    assert canonical_json_bytes(value) == (
        b'{"amount_atomic":1000000,"enabled":true,'
        b'"nested":{"a":"\xc3\xa9","b":["x",2,null]}}'
    )


def test_canonical_json_bytes_uses_unicode_codepoint_key_order():
    value = {"\U00010000": 4, "\ue000": 3, "é": 2, "a": 1}

    assert canonical_json_bytes(value) == (
        '{"a":1,"é":2,"":3,"𐀀":4}'.encode("utf-8")
    )


def test_canonical_json_bytes_enforces_ijson_safe_integer_range():
    safe = (1 << 53) - 1
    assert canonical_json_bytes({"negative": -safe, "positive": safe}) == (
        b'{"negative":-9007199254740991,"positive":9007199254740991}'
    )

    for value in (-safe - 1, safe + 1):
        with pytest.raises(ValueError, match="safe integer"):
            canonical_json_bytes(value)


@pytest.mark.parametrize("value", ["\ud800", "\ufdd0", "\U0001fffe", {"\ud800": 1}])
def test_canonical_json_bytes_rejects_surrogates_and_noncharacters(value):
    with pytest.raises(ValueError, match="canonical JSON"):
        canonical_json_bytes(value)


@pytest.mark.parametrize(
    "value",
    [
        {"fraction": 1.5},
        {"decimal": Decimal("1.0")},
        {1: "non-string key"},
        ["ok", 1.5],
    ],
)
def test_canonical_json_bytes_rejects_non_canonical_values(value):
    with pytest.raises(ValueError, match="canonical JSON"):
        canonical_json_bytes(value)


@pytest.mark.parametrize("amount", ["0", "1.0", "-1", "+1", "01", "", 1])
def test_amount_must_be_a_canonical_atomic_integer_string(amount):
    with pytest.raises(ValueError, match="amount_atomic"):
        valid_envelope(amount_atomic=amount)


@pytest.mark.parametrize(
    "field",
    ["wallet_address", "asset_contract", "pay_to", "executor_contract"],
)
def test_addresses_are_canonicalized(field):
    address = (
        "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
        if field == "asset_contract"
        else "0x" + "AB" * 20
    )
    envelope = valid_envelope(**{field: address})

    expected = HOSTED_BASE_USDC if field == "asset_contract" else "0x" + "ab" * 20
    assert getattr(envelope, field) == expected


def test_envelope_rejects_unknown_fields_and_overlong_validity():
    with pytest.raises(ValueError):
        valid_envelope(untrusted_override="x")
    with pytest.raises(ValueError, match="validity window"):
        valid_envelope(issued_at=100, expires_at=161)


@pytest.mark.parametrize(
    "field",
    [
        "spending_grant_hash",
        "policy_snapshot_hash",
        "risk_evidence_hash",
        "payment_capability_hash",
        "quote_hash",
        "payment_challenge_hash",
        "execution_scope_hash",
        "request_nonce",
    ],
)
@pytest.mark.parametrize(
    "value",
    ["0x" + "a" * 63, "0x" + "A" * 64, "0x" + "g" * 64, "hash"],
)
def test_required_hashes_must_be_lowercase_bytes32(field, value):
    with pytest.raises(ValueError, match=field):
        valid_envelope(**{field: value})


@pytest.mark.parametrize(
    "field",
    [
        "audience",
        "request_id",
        "idempotency_key",
        "tenant_id",
        "node_id",
        "wallet_binding_id",
        "payment_capability_id",
        "wallet_identity_id",
        "spending_grant_id",
        "asset_allowance_id",
        "reservation_id",
        "action_id",
        "policy_decision_id",
        "purchase_id",
        "merchant_id",
    ],
)
@pytest.mark.parametrize("value", ["", "\ninvalid", "x" * 257])
def test_identifiers_are_nonempty_bounded_and_control_character_free(field, value):
    with pytest.raises(ValueError, match=field):
        valid_envelope(**{field: value})


@pytest.mark.parametrize(
    "request_id",
    ["request/value", "%2F", "%252F", "white space", "请求", ".", ".."],
)
def test_request_id_is_a_reversible_ascii_path_segment(request_id):
    with pytest.raises(ValueError, match="request_id"):
        valid_envelope(request_id=request_id)


@pytest.mark.parametrize("request_id", ["a", "Request_1-valid", "x" * 256])
def test_request_id_accepts_existing_ascii_identifier_grammar(request_id):
    assert valid_envelope(request_id=request_id).request_id == request_id


@pytest.mark.parametrize(
    "field, value",
    [
        ("audience", "another-facilitator"),
        ("protocol_version", "other"),
        ("payment_capability_version", "other"),
        ("http_method", "GET"),
        ("http_path", "/other"),
    ],
)
def test_protocol_and_hosted_route_reject_unapproved_values(field, value):
    with pytest.raises(ValueError, match=field):
        valid_envelope(**{field: value})


@pytest.mark.parametrize("path", ["/v1/preflight", "/v1/executions"])
def test_hosted_route_is_signed_into_request_hash(path):
    envelope = valid_envelope(http_path=path)
    assert envelope.http_path == path
    if path == "/v1/preflight":
        assert envelope.request_hash == valid_envelope().request_hash
    else:
        assert envelope.request_hash != valid_envelope().request_hash


@pytest.mark.parametrize(
    "issued_at, expires_at",
    [(0, 1), (-1, 1), (100, 100), (100, 99)],
)
def test_envelope_timestamps_must_be_positive_and_ordered(issued_at, expires_at):
    with pytest.raises(ValueError):
        valid_envelope(issued_at=issued_at, expires_at=expires_at)


@pytest.mark.parametrize(
    ("field", "value"),
    [("issued_at", 100.0), ("expires_at", "160"), ("issued_at", True)],
)
def test_envelope_direct_construction_rejects_non_integer_timestamps(field, value):
    with pytest.raises(ValueError, match=field):
        valid_envelope(**{field: value})


def test_validate_payment_window_rejects_expired_and_future_envelopes():
    with pytest.raises(ValueError, match="expired"):
        validate_payment_window(valid_envelope(), now=160)
    with pytest.raises(ValueError, match="future"):
        validate_payment_window(valid_envelope(), now=99)


def test_validate_payment_window_accepts_the_issued_validity_interval():
    envelope = valid_envelope()

    validate_payment_window(envelope, now=100)
    validate_payment_window(envelope, now=159)
    assert MAX_PAYMENT_VALIDITY_SECONDS == 60


def test_device_identity_survives_private_key_round_trip():
    created = DeviceSigningKey.generate()
    loaded = DeviceSigningKey.from_pkcs8_der(created.pkcs8_der)

    assert loaded.public_jwk == created.public_jwk
    assert loaded.thumbprint == created.thumbprint
    assert created.public_jwk.keys() == {"kty", "crv", "x", "y"}
    assert created.public_jwk["kty"] == "EC"
    assert created.public_jwk["crv"] == "P-256"


def test_payment_envelope_signs_and_verifies_with_strict_headers():
    key = DeviceSigningKey.generate()
    token = sign_payment_envelope(key, valid_envelope())

    assert jwt.get_unverified_header(token) == {
        "alg": "ES256",
        "kid": key.thumbprint,
        "typ": "clink-payment+jwt",
    }
    assert verify_payment_envelope(token, key.public_jwk, now=100) == valid_envelope()


def test_preflight_response_signature_verification_binds_server_key():
    key = DeviceSigningKey.generate()
    expected = valid_envelope()
    response = HostedPreflightResponse(
        provider_request_id="provider_1",
        request_id=expected.request_id,
        request_hash=expected.request_hash,
        idempotency_key=expected.idempotency_key,
        state="dry_run_accepted",
        chain_id=expected.chain_id,
        asset_contract=expected.asset_contract,
        amount_atomic=expected.amount_atomic,
        pay_to=expected.pay_to,
        transaction_hash=None,
        submitted_at=None,
        confirmed_at=None,
        server_key_id=key.thumbprint,
    )
    signed = sign_preflight_response(key, response)

    assert verify_preflight_response(signed, key.public_jwk, expected) == response

    with pytest.raises(HostedProtocolError, match="response"):
        verify_preflight_response(signed, DeviceSigningKey.generate().public_jwk, expected)


def test_preflight_response_rejected_state_cannot_authorize_execution():
    key = DeviceSigningKey.generate()
    expected = valid_envelope()
    response = HostedPreflightResponse(
        provider_request_id=expected.request_id,
        request_id=expected.request_id,
        request_hash=expected.request_hash,
        idempotency_key=expected.idempotency_key,
        state="rejected",
        chain_id=expected.chain_id,
        asset_contract=expected.asset_contract,
        amount_atomic=expected.amount_atomic,
        pay_to=expected.pay_to,
        transaction_hash=None,
        submitted_at=None,
        confirmed_at=None,
        server_key_id=key.thumbprint,
    )
    signed = sign_preflight_response(key, response)

    with pytest.raises(HostedProtocolError, match="dry_run_accepted"):
        verify_preflight_response(signed, key.public_jwk, expected)


@pytest.mark.parametrize(
    ("field", "updates"),
    [
        ("request_id", {"request_id": "request_2"}),
        ("request_hash", {"request_hash": "0x" + "99" * 32}),
        ("idempotency_key", {"idempotency_key": "idempotency_2"}),
        (
            "chain_id",
            {"chain_id": "eip155:137", "asset_contract": HOSTED_POLYGON_USDC},
        ),
        ("amount_atomic", {"amount_atomic": "1000001"}),
        ("pay_to", {"pay_to": "0x" + "66" * 20}),
    ],
)
def test_preflight_response_must_match_expected_request_scope(field, updates):
    key = DeviceSigningKey.generate()
    expected = valid_envelope()
    response = HostedPreflightResponse(
        provider_request_id="provider_1",
        request_id=expected.request_id,
        request_hash=expected.request_hash,
        idempotency_key=expected.idempotency_key,
        state="dry_run_accepted",
        chain_id=expected.chain_id,
        asset_contract=expected.asset_contract,
        amount_atomic=expected.amount_atomic,
        pay_to=expected.pay_to,
        transaction_hash=None,
        submitted_at=None,
        confirmed_at=None,
        server_key_id=key.thumbprint,
    ).model_copy(update=updates)
    signed = sign_preflight_response(key, response)

    with pytest.raises(HostedProtocolError, match=field):
        verify_preflight_response(signed, key.public_jwk, expected)


def test_preflight_response_rejects_cross_chain_token_pair() -> None:
    key = DeviceSigningKey.generate()
    expected = valid_envelope()

    with pytest.raises(ValueError, match="canonical USDC"):
        HostedPreflightResponse(
            provider_request_id="provider_1",
            request_id=expected.request_id,
            request_hash=expected.request_hash,
            idempotency_key=expected.idempotency_key,
            state="dry_run_accepted",
            chain_id=expected.chain_id,
            asset_contract=HOSTED_POLYGON_USDC,
            amount_atomic=expected.amount_atomic,
            pay_to=expected.pay_to,
            transaction_hash=None,
            submitted_at=None,
            confirmed_at=None,
            server_key_id=key.thumbprint,
        )


def test_preflight_response_rejects_zero_amount():
    key = DeviceSigningKey.generate()
    expected = valid_envelope()

    with pytest.raises(ValueError, match="amount_atomic"):
        HostedPreflightResponse(
            provider_request_id="provider_1",
            request_id=expected.request_id,
            request_hash=expected.request_hash,
            idempotency_key=expected.idempotency_key,
            state="dry_run_accepted",
            chain_id=expected.chain_id,
            asset_contract=expected.asset_contract,
            amount_atomic="0",
            pay_to=expected.pay_to,
            transaction_hash=None,
            submitted_at=None,
            confirmed_at=None,
            server_key_id=key.thumbprint,
        )


def valid_execution_envelope(**overrides: object) -> HostedPaymentEnvelope:
    values = {
        **valid_envelope().model_dump(),
        "http_path": "/v1/executions",
        "chain_id": "eip155:8453",
        "asset_contract": "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
    }
    values.update(overrides)
    return HostedPaymentEnvelope(**values)


def valid_execution_response(
    key: DeviceSigningKey,
    envelope: HostedPaymentEnvelope | None = None,
    **overrides: object,
) -> HostedExecutionResponse:
    envelope = envelope or valid_execution_envelope()
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
        "server_key_id": key.thumbprint,
    }
    values.update(overrides)
    return HostedExecutionResponse(**values)


def valid_release_evidence(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "receipt_status": 0,
        "canonical_receipt": True,
        "finality_boundary_timestamp": 161,
        "capability_used": False,
        "owner_nonce_used": False,
        "payment_event_found": False,
        "transfer_event_found": False,
    }
    values.update(overrides)
    return values


def valid_chain_released_response(
    key: DeviceSigningKey,
    envelope: HostedPaymentEnvelope | None = None,
    **overrides: object,
) -> HostedExecutionResponse:
    values: dict[str, object] = {
        "state": "released",
        "receipt_block_hash": "0x" + "bb" * 32,
        "receipt_block_number": 100,
        "safe_block_hash": "0x" + "cc" * 32,
        "safe_block_number": 102,
        "confirmations": 2,
        "reverted_at": 103,
        "released_at": 161,
        "failure_reason_code": "SAFE_RELEASE",
        "finality_boundary": "safe",
        "release_evidence": valid_release_evidence(),
    }
    values.update(overrides)
    return valid_execution_response(key, envelope, **values)


def valid_unsigned_expired_response(
    key: DeviceSigningKey,
    envelope: HostedPaymentEnvelope | None = None,
    **overrides: object,
) -> HostedExecutionResponse:
    envelope = envelope or valid_execution_envelope()
    values: dict[str, object] = {
        "state": "expired",
        "transaction_hash": None,
        "submitted_at": None,
        "receipt_block_hash": None,
        "receipt_block_number": None,
        "safe_block_hash": None,
        "safe_block_number": None,
        "confirmations": 0,
        "failure_reason_code": "UNSIGNED_EXECUTION_EXPIRED",
        "confirmed_at": None,
        "finalized_at": None,
        "reverted_at": None,
        "reorg_reviewed_at": None,
        "released_at": None,
        "expired_at": envelope.expires_at,
        "watcher_version": None,
        "finality_boundary": None,
        "release_evidence": None,
    }
    values.update(overrides)
    return valid_execution_response(key, envelope, **values)


@pytest.mark.parametrize("released_at", [None, 160])
def test_unsigned_expiry_attestation_accepts_expired_and_released_timestamps(
    released_at: int | None,
) -> None:
    key = DeviceSigningKey.generate()
    expected = valid_execution_envelope()

    response = valid_unsigned_expired_response(
        key,
        expected,
        released_at=released_at,
    )
    signed = sign_execution_response(key, response)

    verified = verify_execution_response(
        signed,
        key.public_jwk,
        expected,
        now=expected.expires_at,
    )

    assert verified.state == "expired"
    assert verified.failure_reason_code == "UNSIGNED_EXECUTION_EXPIRED"
    assert verified.expired_at == expected.expires_at
    assert verified.released_at == released_at


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("transaction_hash", "0x" + "aa" * 32),
        ("submitted_at", 160),
        ("receipt_block_hash", "0x" + "bb" * 32),
        ("receipt_block_number", 100),
        ("safe_block_hash", "0x" + "cc" * 32),
        ("safe_block_number", 100),
        ("confirmations", 1),
        ("confirmed_at", 160),
        ("finalized_at", 160),
        ("reverted_at", 160),
        ("reorg_reviewed_at", 160),
        ("watcher_version", "hosted-base-watcher-v1"),
        ("finality_boundary", "safe"),
        ("release_evidence", valid_release_evidence()),
    ],
)
def test_unsigned_expiry_attestation_rejects_any_outcome_evidence(
    field: str,
    replacement: object,
) -> None:
    key = DeviceSigningKey.generate()

    with pytest.raises(ValueError, match=field):
        valid_unsigned_expired_response(key, **{field: replacement})


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("expired_at", 159),
        ("expired_at", 100),
        ("released_at", 161),
    ],
)
def test_unsigned_expiry_attestation_rejects_invalid_terminal_timestamp(
    field: str,
    replacement: int,
) -> None:
    key = DeviceSigningKey.generate()

    with pytest.raises(ValueError, match="expired|timestamp|ordered"):
        valid_unsigned_expired_response(key, **{field: replacement})


def test_unsigned_expiry_attestation_rejects_non_expired_state() -> None:
    key = DeviceSigningKey.generate()

    with pytest.raises(ValueError, match="only valid for expired"):
        valid_execution_response(
            key,
            state="submitted",
            failure_reason_code="UNSIGNED_EXECUTION_EXPIRED",
        )


def test_unsigned_expiry_attestation_reason_is_not_valid_for_released_state() -> None:
    key = DeviceSigningKey.generate()

    with pytest.raises(ValueError, match="only valid for expired"):
        valid_chain_released_response(
            key,
            failure_reason_code="UNSIGNED_EXECUTION_EXPIRED",
        )


def test_unsigned_expiry_attestation_rejects_future_expiry_at_verification() -> None:
    key = DeviceSigningKey.generate()
    expected = valid_execution_envelope()
    response = valid_unsigned_expired_response(
        key,
        expected,
        expired_at=expected.expires_at + 1,
    )
    signed = sign_execution_response(key, response)

    with pytest.raises(HostedProtocolError, match="future"):
        verify_execution_response(
            signed,
            key.public_jwk,
            expected,
            now=expected.expires_at,
        )


def test_legacy_generic_expiry_remains_compatible() -> None:
    key = DeviceSigningKey.generate()

    response = valid_execution_response(
        key,
        state="expired",
        transaction_hash=None,
        submitted_at=None,
        expired_at=103,
        failure_reason_code="AUTHORIZATION_EXPIRED",
    )

    assert response.failure_reason_code == "AUTHORIZATION_EXPIRED"


def test_released_chain_execution_requires_strict_revert_release_evidence() -> None:
    key = DeviceSigningKey.generate()

    response = valid_chain_released_response(key)

    assert response.state == "released"
    assert response.release_evidence.model_dump(mode="json") == valid_release_evidence()


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("receipt_status", 1),
        ("canonical_receipt", False),
        ("finality_boundary_timestamp", 159),
        ("capability_used", True),
        ("owner_nonce_used", True),
        ("payment_event_found", True),
        ("transfer_event_found", True),
    ],
)
def test_revert_release_evidence_rejects_unsafe_values(
    field: str, replacement: object
) -> None:
    key = DeviceSigningKey.generate()

    with pytest.raises(ValueError):
        valid_chain_released_response(
            key,
            release_evidence=valid_release_evidence(**{field: replacement}),
        )


def test_revert_release_evidence_is_forbidden_on_non_released_state() -> None:
    key = DeviceSigningKey.generate()

    with pytest.raises(ValueError, match="release_evidence"):
        valid_execution_response(
            key,
            release_evidence=valid_release_evidence(),
        )


def test_revert_release_evidence_is_frozen_and_accepts_deadline_boundary() -> None:
    key = DeviceSigningKey.generate()
    response = valid_chain_released_response(
        key,
        release_evidence=valid_release_evidence(
            finality_boundary_timestamp=160,
        ),
    )

    assert response.release_evidence.finality_boundary_timestamp == response.deadline
    with pytest.raises(ValueError):
        response.release_evidence.finality_boundary_timestamp = 161


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("receipt_status", False),
        ("canonical_receipt", 1),
        ("capability_used", 0),
        ("owner_nonce_used", 0),
        ("payment_event_found", 0),
        ("transfer_event_found", 0),
    ],
)
def test_revert_release_evidence_rejects_bool_integer_aliases(
    field: str, replacement: object
) -> None:
    key = DeviceSigningKey.generate()

    with pytest.raises(ValueError, match=field):
        valid_chain_released_response(
            key,
            release_evidence=valid_release_evidence(**{field: replacement}),
        )


def test_execution_response_rejects_future_release_boundary() -> None:
    key = DeviceSigningKey.generate()
    expected = valid_execution_envelope()
    response = valid_chain_released_response(
        key,
        expected,
        release_evidence=valid_release_evidence(
            finality_boundary_timestamp=expected.expires_at,
        ),
    )
    signed = sign_execution_response(key, response)

    with pytest.raises(HostedProtocolError, match="future"):
        verify_execution_response(
            signed,
            key.public_jwk,
            expected,
            now=expected.expires_at - 1,
        )


@pytest.mark.parametrize(
    "updates",
    [
        {"receipt_block_hash": None},
        {"receipt_block_number": None},
        {"safe_block_hash": None},
        {"safe_block_number": None},
        {"confirmations": 1},
        {"finality_boundary": None},
        {"reverted_at": None},
        {"released_at": None},
        {"release_evidence": None},
        {
            "release_evidence": {
                **valid_release_evidence(),
                "untrusted": False,
            }
        },
    ],
)
def test_released_execution_requires_complete_safe_release_proof(
    updates: dict[str, object],
) -> None:
    key = DeviceSigningKey.generate()

    with pytest.raises(ValueError):
        valid_chain_released_response(key, **updates)


def test_execution_response_signature_verification_binds_base_execution_scope():
    key = DeviceSigningKey.generate()
    expected = valid_execution_envelope()
    response = valid_execution_response(key, expected)
    signed = sign_execution_response(key, response)

    assert jwt.get_unverified_header(signed) == {
        "alg": "ES256",
        "kid": key.thumbprint,
        "typ": "clink-execution-response+jwt",
    }
    assert verify_execution_response(signed, key.public_jwk, expected, now=103) == response


def test_execution_response_carries_signed_watcher_version() -> None:
    key = DeviceSigningKey.generate()
    expected = valid_execution_envelope()
    response = valid_execution_response(
        key,
        expected,
        watcher_version="hosted-base-watcher-v1",
    )
    signed = sign_execution_response(key, response)

    verified = verify_execution_response(signed, key.public_jwk, expected, now=103)

    assert verified.watcher_version == "hosted-base-watcher-v1"


@pytest.mark.parametrize(
    "state_updates",
    [
        {
            "state": "submission_unknown",
        },
        {
            "state": "submission_rejected",
            "failure_reason_code": "RPC_REJECTED",
        },
        {
            "state": "confirmed",
            "receipt_block_hash": "0x" + "bb" * 32,
            "receipt_block_number": 100,
            "confirmations": 1,
            "confirmed_at": 103,
            "finality_boundary": "safe",
        },
        {
            "state": "finalized",
            "receipt_block_hash": "0x" + "bb" * 32,
            "receipt_block_number": 100,
            "safe_block_hash": "0x" + "cc" * 32,
            "safe_block_number": 102,
            "confirmations": 2,
            "confirmed_at": 103,
            "finalized_at": 104,
            "finality_boundary": "safe",
        },
        {
            "state": "reverted",
            "receipt_block_hash": "0x" + "bb" * 32,
            "receipt_block_number": 100,
            "safe_block_hash": "0x" + "cc" * 32,
            "safe_block_number": 102,
            "confirmations": 2,
            "reverted_at": 103,
            "failure_reason_code": "ONCHAIN_REVERT",
            "finality_boundary": "safe",
        },
        {
            "state": "reorg_review",
            "receipt_block_hash": "0x" + "bb" * 32,
            "receipt_block_number": 100,
            "reorg_reviewed_at": 103,
            "failure_reason_code": "REORG_DETECTED",
            "finality_boundary": "safe",
        },
        {
            "state": "rejected",
            "transaction_hash": None,
            "submitted_at": None,
            "failure_reason_code": "POLICY_BLOCKED",
        },
        {
            "state": "released",
            "receipt_block_hash": "0x" + "bb" * 32,
            "receipt_block_number": 100,
            "safe_block_hash": "0x" + "cc" * 32,
            "safe_block_number": 102,
            "confirmations": 2,
            "reverted_at": 103,
            "released_at": 161,
            "failure_reason_code": "SAFE_RELEASE",
            "finality_boundary": "safe",
            "release_evidence": valid_release_evidence(),
        },
        {
            "state": "expired",
            "transaction_hash": None,
            "submitted_at": None,
            "expired_at": 103,
            "failure_reason_code": "AUTHORIZATION_EXPIRED",
        },
    ],
)
def test_execution_response_accepts_each_bounded_state(
    state_updates: dict[str, object],
) -> None:
    key = DeviceSigningKey.generate()
    response = valid_execution_response(key, **state_updates)
    assert response.state == state_updates["state"]


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("request_id", "request_2"),
        ("request_hash", "0x" + "99" * 32),
        ("idempotency_key", "idempotency_2"),
        ("capability_id", "capability_2"),
        ("capability_hash", "0x" + "99" * 32),
        ("reservation_id", "reservation_2"),
        ("reservation_hash", "0x" + "98" * 32),
        ("purchase_id", "purchase_2"),
        ("execution_scope_hash", "0x" + "99" * 32),
        ("owner", "0x" + "55" * 20),
        ("payee", "0x" + "66" * 20),
        ("token", "0x" + "77" * 20),
        ("amount_atomic", "1000001"),
        ("executor", "0x" + "88" * 20),
        ("owner_nonce", "0x" + "09" * 32),
        ("deadline", 159),
    ],
)
def test_execution_response_must_match_every_expected_execution_scope_field(
    field: str, replacement: object
) -> None:
    key = DeviceSigningKey.generate()
    expected = valid_execution_envelope()
    response = valid_execution_response(key, expected).model_copy(
        update={field: replacement}
    )
    signed = sign_execution_response(key, response)

    with pytest.raises(HostedProtocolError, match=("payload|" + field)):
        verify_execution_response(signed, key.public_jwk, expected, now=103)


def test_execution_response_rejects_wrong_route_or_server_key() -> None:
    key = DeviceSigningKey.generate()
    expected = valid_execution_envelope()
    signed = sign_execution_response(key, valid_execution_response(key, expected))

    with pytest.raises(HostedProtocolError, match="route"):
        verify_execution_response(signed, key.public_jwk, expected.model_copy(update={"http_path": "/v1/preflight"}))
    with pytest.raises(HostedProtocolError, match="key"):
        verify_execution_response(signed, DeviceSigningKey.generate().public_jwk, expected)


def test_execution_response_can_bind_server_execution_identity_explicitly() -> None:
    key = DeviceSigningKey.generate()
    expected = valid_execution_envelope()
    signed = sign_execution_response(key, valid_execution_response(key, expected))

    assert verify_execution_response(
        signed, key.public_jwk, expected, expected_execution_id="execution_1"
    ).execution_id == "execution_1"
    with pytest.raises(HostedProtocolError, match="execution ID"):
        verify_execution_response(
            signed, key.public_jwk, expected, expected_execution_id="execution_2"
        )


@pytest.mark.parametrize(
    "updates",
    [
        {"transaction_hash": None},
        {"state": "confirmed", "confirmed_at": 103},
        {
            "state": "confirmed",
            "receipt_block_hash": "0x" + "bb" * 32,
            "receipt_block_number": 100,
            "confirmations": 0,
            "confirmed_at": 103,
        },
        {
            "state": "finalized",
            "receipt_block_hash": "0x" + "bb" * 32,
            "receipt_block_number": 100,
            "safe_block_hash": "0x" + "cc" * 32,
            "safe_block_number": 100,
            "confirmations": 1,
            "confirmed_at": 103,
            "finalized_at": 102,
        },
        {"failure_reason_code": "free text"},
        {"state": "reverted"},
        {"state": "submission_rejected", "failure_reason_code": None},
        {"state": "released", "failure_reason_code": "RPC_REJECTED"},
        {"state": "expired", "transaction_hash": None, "submitted_at": None},
        {
            "state": "reverted",
            "receipt_block_hash": "0x" + "bb" * 32,
            "receipt_block_number": 100,
            "reverted_at": 103,
            "failure_reason_code": "ONCHAIN_REVERT",
        },
        {"state": "reorg_review", "receipt_block_hash": None},
        {
            "state": "rejected",
            "transaction_hash": "0x" + "aa" * 32,
            "failure_reason_code": "POLICY_BLOCKED",
        },
    ],
)
def test_execution_response_rejects_malformed_state_combinations(
    updates: dict[str, object],
) -> None:
    key = DeviceSigningKey.generate()
    with pytest.raises(ValueError):
        HostedExecutionResponse(
            **{
                **valid_execution_response(key).model_dump(),
                **updates,
            }
        )


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("execution_id", "执行"),
        ("failure_reason_code", "bad reason"),
        ("issued_at", True),
        ("deadline", 1 << 53),
        ("confirmations", 1.0),
    ],
)
def test_execution_response_enforces_ascii_and_ijson_bounds(
    field: str, replacement: object
) -> None:
    key = DeviceSigningKey.generate()
    with pytest.raises(ValueError, match=field):
        valid_execution_response(key, **{field: replacement})


def test_execution_response_rejects_time_drift_and_success_failure_code() -> None:
    key = DeviceSigningKey.generate()
    expected = valid_execution_envelope()
    future = valid_execution_response(
        key,
        expected,
        issued_at=expected.expires_at + 1,
        submitted_at=expected.expires_at + 2,
    )
    signed = sign_execution_response(key, future)

    with pytest.raises(HostedProtocolError, match="time"):
        verify_execution_response(signed, key.public_jwk, expected, now=expected.expires_at)

    with pytest.raises(ValueError, match="failure"):
        valid_execution_response(key, state="submitted", failure_reason_code="RPC_TIMEOUT")


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("amount_atomic", "2"),
        ("pay_to", "0x" + "9" * 40),
        ("asset_contract", "0x" + "8" * 40),
        ("chain_id", "eip155:8453"),
        ("quote_hash", "0x" + "7" * 64),
        ("expires_at", 101),
    ],
)
def test_any_payment_payload_tamper_breaks_signature(field, replacement):
    key = DeviceSigningKey.generate()
    signed = sign_payment_envelope(key, valid_envelope())
    tampered = replace_compact_jws_payload(signed, field, replacement)

    with pytest.raises(HostedProtocolError, match="signature"):
        verify_payment_envelope(tampered, key.public_jwk, now=100)


def test_payment_signed_by_another_device_is_rejected():
    trusted = DeviceSigningKey.generate()
    attacker = DeviceSigningKey.generate()

    with pytest.raises(HostedProtocolError, match="signature"):
        verify_payment_envelope(
            sign_payment_envelope(attacker, valid_envelope()),
            trusted.public_jwk,
            now=100,
        )


def test_payment_rejects_correctly_signed_wrong_kid():
    key = DeviceSigningKey.generate()
    signed = sign_payment_envelope(key, valid_envelope())
    wrong_kid = resign_token(key, signed, header_overrides={"kid": "wrong-kid"})

    with pytest.raises(HostedProtocolError, match="device key"):
        verify_payment_envelope(wrong_kid, key.public_jwk, now=100)


def test_non_ascii_payment_kid_is_a_secret_free_protocol_error():
    key = DeviceSigningKey.generate()
    signed = sign_payment_envelope(key, valid_envelope())
    attacker_kid = "é"
    wrong_kid = resign_token(key, signed, header_overrides={"kid": attacker_kid})

    with pytest.raises(HostedProtocolError) as caught:
        verify_payment_envelope(wrong_kid, key.public_jwk, now=100)

    assert attacker_kid not in str(caught.value)
    assert wrong_kid not in str(caught.value)


@pytest.mark.parametrize(
    ("overrides", "now"),
    [
        ({"issued_at": "100"}, 100),
        ({"expires_at": "160"}, 100),
        ({"issued_at": True, "expires_at": 2}, 1),
    ],
)
def test_signed_payment_timestamps_are_not_coerced(overrides, now):
    key = DeviceSigningKey.generate()
    token = resign_token(
        key,
        sign_payment_envelope(key, valid_envelope()),
        claim_overrides=overrides,
    )

    with pytest.raises(HostedProtocolError, match="payload"):
        verify_payment_envelope(token, key.public_jwk, now=now)


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("audience", "another-facilitator"),
        ("http_path", "/v1/execute"),
        ("http_method", "GET"),
    ],
)
def test_signed_payment_scope_is_fixed(field, replacement):
    key = DeviceSigningKey.generate()
    token = resign_token(
        key,
        sign_payment_envelope(key, valid_envelope()),
        claim_overrides={field: replacement},
    )

    with pytest.raises(HostedProtocolError, match="payment"):
        verify_payment_envelope(token, key.public_jwk, now=100)


def test_payment_rejects_unknown_jws_type_and_expiration():
    key = DeviceSigningKey.generate()
    signed = sign_payment_envelope(key, valid_envelope())
    unknown_type = resign_token(key, signed, header_overrides={"typ": "JWT"})

    with pytest.raises(HostedProtocolError, match="type"):
        verify_payment_envelope(unknown_type, key.public_jwk, now=100)
    with pytest.raises(HostedProtocolError, match="expired"):
        verify_payment_envelope(signed, key.public_jwk, now=160)


@pytest.mark.parametrize("algorithm", ["none", "HS256"])
def test_payment_rejects_non_es256_algorithms(algorithm):
    key = DeviceSigningKey.generate()
    invalid = compact_jws(
        {
            "alg": algorithm,
            "typ": "clink-payment+jwt",
            "kid": key.thumbprint,
        },
        valid_envelope().canonical_bytes(),
    )

    with pytest.raises(HostedProtocolError, match="algorithm"):
        verify_payment_envelope(invalid, key.public_jwk, now=100)


def test_dpop_proof_signs_and_verifies_normalized_request_claims():
    key = DeviceSigningKey.generate()
    proof = build_dpop_proof(
        key,
        method="post",
        url="HTTPS://PAY.ECHOOO.CC:443/v1/preflight?ignored=yes#fragment",
        access_token="opaque-test-token",
        now=100,
        jti="jti-1",
    )

    assert jwt.get_unverified_header(proof) == {
        "alg": "ES256",
        "jwk": key.public_jwk,
        "typ": "dpop+jwt",
    }
    claims = verify_dpop_proof(
        proof,
        trusted_public_jwk=key.public_jwk,
        method="POST",
        url="https://pay.echooo.cc/v1/preflight",
        access_token="opaque-test-token",
        now=100,
    )
    assert claims == DPoPClaims(
        htu="https://pay.echooo.cc/v1/preflight",
        htm="POST",
        iat=100,
        jti="jti-1",
        ath=base64url(hashlib.sha256(b"opaque-test-token").digest()),
    )


@pytest.mark.parametrize(
    "url",
    [
        "http://pay.echooo.cc/v1/preflight",
        "http://localhost.evil/v1/preflight",
        "http://127.0.0.1.evil/v1/preflight",
    ],
)
def test_dpop_rejects_non_loopback_plain_http(url):
    with pytest.raises(HostedProtocolError, match="URI"):
        build_dpop_proof(
            DeviceSigningKey.generate(),
            method="POST",
            url=url,
            access_token="opaque-test-token",
            now=100,
            jti="jti-http-rejected",
        )


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost/v1/preflight",
        "http://127.0.0.1/v1/preflight",
        "http://127.255.255.255/v1/preflight",
        "http://[::1]/v1/preflight",
    ],
)
def test_dpop_allows_plain_http_only_for_explicit_loopback(url):
    key = DeviceSigningKey.generate()
    proof = build_dpop_proof(
        key,
        method="POST",
        url=url,
        access_token="opaque-test-token",
        now=100,
        jti="jti-loopback",
    )

    assert verify_dpop_proof(
        proof,
        trusted_public_jwk=key.public_jwk,
        method="POST",
        url=url,
        access_token="opaque-test-token",
        now=100,
    ).jti == "jti-loopback"


def test_stolen_access_token_cannot_be_used_by_another_device():
    expected = DeviceSigningKey.generate()
    attacker = DeviceSigningKey.generate()
    proof = build_dpop_proof(
        attacker,
        method="POST",
        url="https://pay.echooo.cc/v1/preflight",
        access_token="opaque-test-token",
        now=100,
        jti="jti-attacker",
    )

    with pytest.raises(HostedProtocolError, match="device key"):
        verify_dpop_proof(
            proof,
            trusted_public_jwk=expected.public_jwk,
            method="POST",
            url="https://pay.echooo.cc/v1/preflight",
            access_token="opaque-test-token",
            now=100,
        )


def test_unicode_dpop_htu_is_a_secret_free_protocol_error():
    key = DeviceSigningKey.generate()
    access_token = "opaque-unicode-test-token"
    request_url = "https://pay.echooo.cc/préflight"
    proof = build_dpop_proof(
        key,
        method="POST",
        url=request_url,
        access_token=access_token,
        now=100,
        jti="jti-unicode",
    )

    with pytest.raises(HostedProtocolError) as caught:
        verify_dpop_proof(
            proof,
            trusted_public_jwk=key.public_jwk,
            method="POST",
            url="https://pay.echooo.cc/v1/preflight",
            access_token=access_token,
            now=100,
        )

    assert access_token not in str(caught.value)
    assert proof not in str(caught.value)


def test_missing_dpop_is_rejected():
    key = DeviceSigningKey.generate()

    with pytest.raises(HostedProtocolError, match="required"):
        verify_dpop_proof(
            "",
            trusted_public_jwk=key.public_jwk,
            method="POST",
            url="https://pay.echooo.cc/v1/preflight",
            access_token="opaque-test-token",
            now=100,
        )


@pytest.mark.parametrize(
    ("claim", "replacement", "message"),
    [
        ("htu", "https://pay.echooo.cc/v1/other", "URI"),
        ("htm", "GET", "method"),
        ("ath", "not-the-token-hash", "token hash"),
        ("iat", 39, "old"),
        ("iat", 106, "future"),
        ("jti", "", "jti"),
    ],
)
def test_dpop_rejects_wrong_or_unbounded_claims(claim, replacement, message):
    key = DeviceSigningKey.generate()
    proof = build_dpop_proof(
        key,
        method="POST",
        url="https://pay.echooo.cc/v1/preflight",
        access_token="opaque-test-token",
        now=100,
        jti="jti-1",
    )
    changed = resign_token(key, proof, claim_overrides={claim: replacement})

    with pytest.raises(HostedProtocolError, match=message):
        verify_dpop_proof(
            changed,
            trusted_public_jwk=key.public_jwk,
            method="POST",
            url="https://pay.echooo.cc/v1/preflight",
            access_token="opaque-test-token",
            now=100,
        )


def test_dpop_rejects_missing_and_duplicate_jti_claims():
    key = DeviceSigningKey.generate()
    proof = build_dpop_proof(
        key,
        method="POST",
        url="https://pay.echooo.cc/v1/preflight",
        access_token="opaque-test-token",
        now=100,
        jti="jti-1",
    )
    header = jwt.get_unverified_header(proof)
    claims = jwt.decode(proof, options={"verify_signature": False})
    claims_without_jti = dict(claims)
    claims_without_jti.pop("jti")
    duplicate_payload = canonical_json_bytes(claims)[:-1] + b',"jti":"jti-2"}'
    duplicate = compact_jws(header, duplicate_payload)

    # Re-create rather than update to ensure the claim is truly absent.
    private_key = load_der_private_key(key.pkcs8_der, password=None)
    missing = jwt.encode(claims_without_jti, private_key, algorithm="ES256", headers=header)

    for invalid in (missing, duplicate):
        with pytest.raises(HostedProtocolError, match="jti|duplicate"):
            verify_dpop_proof(
                invalid,
                trusted_public_jwk=key.public_jwk,
                method="POST",
                url="https://pay.echooo.cc/v1/preflight",
                access_token="opaque-test-token",
                now=100,
            )


@pytest.mark.parametrize("algorithm", ["none", "HS256"])
def test_dpop_rejects_non_es256_algorithms(algorithm):
    key = DeviceSigningKey.generate()
    claims = {
        "htu": "https://pay.echooo.cc/v1/preflight",
        "htm": "POST",
        "iat": 100,
        "jti": "jti-1",
        "ath": "irrelevant",
    }
    invalid = compact_jws(
        {"alg": algorithm, "typ": "dpop+jwt", "jwk": key.public_jwk},
        canonical_json_bytes(claims),
    )

    with pytest.raises(HostedProtocolError, match="algorithm"):
        verify_dpop_proof(
            invalid,
            trusted_public_jwk=key.public_jwk,
            method="POST",
            url="https://pay.echooo.cc/v1/preflight",
            access_token="opaque-test-token",
            now=100,
        )


@pytest.mark.parametrize(
    "malformed_jwk",
    [
        {"kty": "oct", "crv": "P-256", "x": "a", "y": "b"},
        {"kty": "EC", "crv": "P-384", "x": "a", "y": "b"},
        {"kty": "EC", "crv": "P-256", "x": "a", "y": "b"},
        {"kty": "EC", "crv": "P-256", "x": "!" * 43, "y": "!" * 43},
    ],
)
def test_malformed_p256_jwk_is_rejected(malformed_jwk):
    key = DeviceSigningKey.generate()
    proof = build_dpop_proof(
        key,
        method="POST",
        url="https://pay.echooo.cc/v1/preflight",
        access_token="opaque-test-token",
        now=100,
        jti="jti-1",
    )

    with pytest.raises(HostedProtocolError, match="public key"):
        verify_dpop_proof(
            proof,
            trusted_public_jwk=malformed_jwk,
            method="POST",
            url="https://pay.echooo.cc/v1/preflight",
            access_token="opaque-test-token",
            now=100,
        )


def test_request_header_malformed_jwk_is_rejected():
    key = DeviceSigningKey.generate()
    proof = build_dpop_proof(
        key,
        method="POST",
        url="https://pay.echooo.cc/v1/preflight",
        access_token="opaque-test-token",
        now=100,
        jti="jti-1",
    )
    malformed = resign_token(
        key,
        proof,
        header_overrides={
            "jwk": {"kty": "EC", "crv": "P-256", "x": "a", "y": "b"}
        },
    )

    with pytest.raises(HostedProtocolError, match="public key"):
        verify_dpop_proof(
            malformed,
            trusted_public_jwk=key.public_jwk,
            method="POST",
            url="https://pay.echooo.cc/v1/preflight",
            access_token="opaque-test-token",
            now=100,
        )


def test_noncanonical_base64url_jwk_coordinate_is_rejected():
    key = DeviceSigningKey.generate()
    noncanonical_jwk = key.public_jwk
    noncanonical_jwk["x"] = noncanonical_base64url_alias(noncanonical_jwk["x"])
    signed = sign_payment_envelope(key, valid_envelope())

    with pytest.raises(HostedProtocolError, match="public key"):
        verify_payment_envelope(signed, noncanonical_jwk, now=100)


def test_protocol_errors_do_not_expose_tokens_jws_or_private_keys():
    key = DeviceSigningKey.generate()
    access_token = "opaque-secret-token-should-not-leak"
    payment_jws = sign_payment_envelope(key, valid_envelope())
    dpop_jws = build_dpop_proof(
        key,
        method="POST",
        url="https://pay.echooo.cc/v1/preflight",
        access_token=access_token,
        now=100,
        jti="jti-secret-test",
    )
    private_bytes = key.pkcs8_der

    failures = []
    for operation in (
        lambda: verify_payment_envelope(payment_jws + "corrupt", key.public_jwk, now=100),
        lambda: verify_dpop_proof(
            dpop_jws,
            trusted_public_jwk=key.public_jwk,
            method="GET",
            url="https://pay.echooo.cc/v1/preflight",
            access_token=access_token,
            now=100,
        ),
    ):
        with pytest.raises(HostedProtocolError) as caught:
            operation()
        failures.append(str(caught.value))

    for message in failures:
        assert access_token not in message
        assert payment_jws not in message
        assert dpop_jws not in message
        assert private_bytes.hex() not in message
