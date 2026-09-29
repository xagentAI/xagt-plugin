from __future__ import annotations

import base64
import json

import pytest

from shared.hosted_facilitator_protocol import DeviceSigningKey
from shared.opc_protocol import (
    OpcProtocolError,
    installation_id,
    sign_opc_proof,
    verify_opc_proof,
)


NOW = 1_788_451_200
ORIGIN = "https://agentonomy.example"


def _segment(value: dict[str, object]) -> str:
    encoded = json.dumps(value, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(encoded).rstrip(b"=").decode("ascii")


def test_opc_proof_round_trip_binds_public_key_origin_action_and_request() -> None:
    key = DeviceSigningKey.generate()

    proof = sign_opc_proof(
        key,
        origin=ORIGIN,
        action="pair",
        request_id="pair-1",
        now=NOW,
        label="Office Linux",
    )

    claims = verify_opc_proof(
        proof,
        origin=ORIGIN,
        action="pair",
        now=NOW + 30,
    )
    assert claims == {
        "aud": ORIGIN,
        "action": "pair",
        "installation_id": installation_id(key.public_jwk),
        "request_id": "pair-1",
        "iat": NOW,
        "exp": NOW + 60,
        "label": "Office Linux",
        "public_jwk": key.public_jwk,
    }


@pytest.mark.parametrize(
    ("origin", "action"),
    [
        ("https://other.example", "pair"),
        (ORIGIN, "token"),
    ],
)
def test_opc_proof_rejects_wrong_origin_or_action(origin: str, action: str) -> None:
    key = DeviceSigningKey.generate()
    proof = sign_opc_proof(
        key,
        origin=ORIGIN,
        action="pair",
        request_id="pair-1",
        now=NOW,
    )

    with pytest.raises(OpcProtocolError):
        verify_opc_proof(proof, origin=origin, action=action, now=NOW)


def test_opc_protocol_rejects_private_jwk_unknown_fields_and_duplicate_json() -> None:
    key = DeviceSigningKey.generate()
    private_header = {
        "alg": "ES256",
        "typ": "agentonomy-opc-proof+jwt",
        "jwk": {**key.public_jwk, "d": "secret"},
    }
    private_proof = key._sign_jwt(
        {
            "aud": ORIGIN,
            "action": "pair",
            "installation_id": installation_id(key.public_jwk),
            "request_id": "pair-1",
            "iat": NOW,
            "exp": NOW + 60,
        },
        private_header,
    )
    with pytest.raises(OpcProtocolError):
        verify_opc_proof(private_proof, origin=ORIGIN, action="pair", now=NOW)

    unknown = key._sign_jwt(
        {
            "aud": ORIGIN,
            "action": "token",
            "installation_id": installation_id(key.public_jwk),
            "request_id": "token-1",
            "iat": NOW,
            "exp": NOW + 60,
            "user_id": "attacker-selected",
        },
        {
            "alg": "ES256",
            "typ": "agentonomy-opc-proof+jwt",
            "jwk": key.public_jwk,
        },
    )
    with pytest.raises(OpcProtocolError):
        verify_opc_proof(unknown, origin=ORIGIN, action="token", now=NOW)

    valid = sign_opc_proof(
        key,
        origin=ORIGIN,
        action="token",
        request_id="token-1",
        now=NOW,
    )
    header, payload, signature = valid.split(".")
    duplicate_payload = (
        '{"aud":"https://agentonomy.example","aud":"https://other.example",'
        '"action":"token","installation_id":"'
        + installation_id(key.public_jwk)
        + '","request_id":"token-1","iat":1788451200,"exp":1788451260}'
    )
    forged = ".".join(
        (
            header,
            base64.urlsafe_b64encode(duplicate_payload.encode())
            .rstrip(b"=")
            .decode(),
            signature,
        )
    )
    with pytest.raises(OpcProtocolError, match="duplicate"):
        verify_opc_proof(forged, origin=ORIGIN, action="token", now=NOW)


def test_opc_protocol_rejects_invalid_time_and_non_origin_urls() -> None:
    key = DeviceSigningKey.generate()
    proof = sign_opc_proof(
        key,
        origin=ORIGIN,
        action="status",
        request_id="status-1",
        now=NOW,
    )
    with pytest.raises(OpcProtocolError, match="expired"):
        verify_opc_proof(proof, origin=ORIGIN, action="status", now=NOW + 91)

    for invalid in (
        "http://agentonomy.example",
        "https://user@agentonomy.example",
        "https://agentonomy.example/path",
        "https://agentonomy.example?query=1",
    ):
        with pytest.raises(OpcProtocolError):
            sign_opc_proof(
                key,
                origin=invalid,
                action="status",
                request_id="status-1",
                now=NOW,
            )

    with pytest.raises(OpcProtocolError):
        sign_opc_proof(
            key,
            origin=ORIGIN,
            action="status",
            request_id="status-1",
            now=True,
        )
