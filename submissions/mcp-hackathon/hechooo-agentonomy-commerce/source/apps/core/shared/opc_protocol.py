from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import json
import re
import unicodedata
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import jwt
from cryptography.hazmat.primitives.asymmetric import ec

from shared.hosted_facilitator_protocol import DeviceSigningKey, canonical_json_bytes


OPC_PROOF_TYPE = "agentonomy-opc-proof+jwt"
OPC_PROOF_TTL_SECONDS = 60
OPC_MAX_CLOCK_SKEW_SECONDS = 30
OPC_ACTIONS = frozenset({"pair", "token", "status", "revoke"})

_BASE64URL = re.compile(r"^[A-Za-z0-9_-]+$")
_REQUEST_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_MAX_PROOF_LENGTH = 16 * 1024


class OpcProtocolError(ValueError):
    """One bounded OPC proof is malformed or does not match its request."""


class _DuplicateJSONKey(ValueError):
    pass


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise _DuplicateJSONKey(key)
        value[key] = item
    return value


def _base64url_decode(value: object, *, expected_length: int | None = None) -> bytes:
    if (
        not isinstance(value, str)
        or not value
        or "=" in value
        or _BASE64URL.fullmatch(value) is None
    ):
        raise OpcProtocolError("OPC proof is malformed")
    try:
        decoded = base64.b64decode(
            value + "=" * (-len(value) % 4),
            altchars=b"-_",
            validate=True,
        )
    except (TypeError, ValueError) as exc:
        raise OpcProtocolError("OPC proof is malformed") from exc
    if expected_length is not None and len(decoded) != expected_length:
        raise OpcProtocolError("OPC proof public key is malformed")
    canonical = base64.urlsafe_b64encode(decoded).rstrip(b"=").decode("ascii")
    if canonical != value:
        raise OpcProtocolError("OPC proof is malformed")
    return decoded


def _decode_json_segment(segment: str, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(
            _base64url_decode(segment).decode("utf-8"),
            object_pairs_hook=_unique_object,
        )
    except _DuplicateJSONKey as exc:
        raise OpcProtocolError(f"{label} contains a duplicate JSON member") from exc
    except (UnicodeDecodeError, ValueError, TypeError) as exc:
        if isinstance(exc, OpcProtocolError):
            raise
        raise OpcProtocolError(f"{label} is malformed") from exc
    if type(value) is not dict:
        raise OpcProtocolError(f"{label} is malformed")
    return value


def _public_key(public_jwk: object) -> ec.EllipticCurvePublicKey:
    if (
        type(public_jwk) is not dict
        or set(public_jwk) != {"kty", "crv", "x", "y"}
        or public_jwk.get("kty") != "EC"
        or public_jwk.get("crv") != "P-256"
    ):
        raise OpcProtocolError("OPC proof public key is malformed")
    x = _base64url_decode(public_jwk.get("x"), expected_length=32)
    y = _base64url_decode(public_jwk.get("y"), expected_length=32)
    try:
        return ec.EllipticCurvePublicNumbers(
            int.from_bytes(x, "big"),
            int.from_bytes(y, "big"),
            ec.SECP256R1(),
        ).public_key()
    except ValueError as exc:
        raise OpcProtocolError("OPC proof public key is malformed") from exc


def _canonical_public_jwk(public_jwk: object) -> dict[str, str]:
    key = _public_key(public_jwk)
    numbers = key.public_numbers()
    return {
        "kty": "EC",
        "crv": "P-256",
        "x": base64.urlsafe_b64encode(numbers.x.to_bytes(32, "big"))
        .rstrip(b"=")
        .decode("ascii"),
        "y": base64.urlsafe_b64encode(numbers.y.to_bytes(32, "big"))
        .rstrip(b"=")
        .decode("ascii"),
    }


def canonical_opc_origin(origin: object, *, allow_loopback_http: bool = False) -> str:
    if type(origin) is not str or not origin or len(origin) > 2048:
        raise OpcProtocolError("OPC origin is invalid")
    if any(ord(character) <= 32 for character in origin):
        raise OpcProtocolError("OPC origin is invalid")
    parsed = urlsplit(origin)
    if (
        parsed.scheme not in {"https", "http"}
        or parsed.username is not None
        or parsed.password is not None
        or not parsed.hostname
        or parsed.path
        or parsed.query
        or parsed.fragment
    ):
        raise OpcProtocolError("OPC origin must be an origin without path or credentials")
    try:
        host = parsed.hostname.encode("idna").decode("ascii").lower()
        port = parsed.port
    except (UnicodeError, ValueError) as exc:
        raise OpcProtocolError("OPC origin is invalid") from exc
    if parsed.scheme == "http":
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            address = None
        if not allow_loopback_http or address is None or not address.is_loopback:
            raise OpcProtocolError("OPC origin must use HTTPS")
    if ":" in host:
        host = f"[{host}]"
    if port is not None and not (
        (parsed.scheme == "https" and port == 443)
        or (parsed.scheme == "http" and port == 80)
    ):
        host = f"{host}:{port}"
    canonical = urlunsplit((parsed.scheme, host, "", "", ""))
    if not hmac.compare_digest(origin.encode("utf-8"), canonical.encode("utf-8")):
        raise OpcProtocolError("OPC origin is not canonical")
    return canonical


def installation_id(public_jwk: dict[str, str]) -> str:
    canonical_jwk = _canonical_public_jwk(public_jwk)
    return "opc_" + hashlib.sha256(canonical_json_bytes(canonical_jwk)).hexdigest()[:40]


def _validate_action(action: object) -> str:
    if type(action) is not str or action not in OPC_ACTIONS:
        raise OpcProtocolError("OPC proof action is invalid")
    return action


def _validate_request_id(request_id: object) -> str:
    if type(request_id) is not str or _REQUEST_ID.fullmatch(request_id) is None:
        raise OpcProtocolError("OPC proof request id is invalid")
    return request_id


def _validate_timestamp(value: object, *, field_name: str) -> int:
    if type(value) is not int or value < 0:
        raise OpcProtocolError(f"OPC proof {field_name} is invalid")
    return value


def _validate_label(label: object) -> str:
    if type(label) is not str or not 1 <= len(label) <= 80:
        raise OpcProtocolError("OPC installation label is invalid")
    if any(
        unicodedata.category(character).startswith("C")
        or unicodedata.category(character) in {"Zl", "Zp"}
        for character in label
    ):
        raise OpcProtocolError("OPC installation label is invalid")
    return label


def sign_opc_proof(
    key: DeviceSigningKey,
    *,
    origin: str,
    action: str,
    request_id: str,
    now: int,
    label: str | None = None,
    allow_loopback_http: bool = False,
) -> str:
    if not isinstance(key, DeviceSigningKey):
        raise OpcProtocolError("OPC device key is invalid")
    canonical_origin = canonical_opc_origin(
        origin, allow_loopback_http=allow_loopback_http
    )
    checked_action = _validate_action(action)
    checked_request_id = _validate_request_id(request_id)
    issued_at = _validate_timestamp(now, field_name="issued at")
    if label is not None and checked_action != "pair":
        raise OpcProtocolError("OPC installation label is allowed only when pairing")
    payload: dict[str, Any] = {
        "aud": canonical_origin,
        "action": checked_action,
        "installation_id": installation_id(key.public_jwk),
        "request_id": checked_request_id,
        "iat": issued_at,
        "exp": issued_at + OPC_PROOF_TTL_SECONDS,
    }
    if label is not None:
        payload["label"] = _validate_label(label)
    return key._sign_jwt(
        payload,
        {
            "alg": "ES256",
            "typ": OPC_PROOF_TYPE,
            "jwk": key.public_jwk,
        },
    )


def verify_opc_proof(
    proof: str,
    *,
    origin: str,
    action: str,
    now: int,
    allow_loopback_http: bool = False,
) -> dict[str, Any]:
    canonical_origin = canonical_opc_origin(
        origin, allow_loopback_http=allow_loopback_http
    )
    checked_action = _validate_action(action)
    current_time = _validate_timestamp(now, field_name="verification time")
    if type(proof) is not str or not proof or len(proof) > _MAX_PROOF_LENGTH:
        raise OpcProtocolError("OPC proof is malformed")
    parts = proof.split(".")
    if len(parts) != 3:
        raise OpcProtocolError("OPC proof is malformed")
    header = _decode_json_segment(parts[0], label="OPC proof header")
    claims = _decode_json_segment(parts[1], label="OPC proof claims")
    if (
        set(header) != {"alg", "typ", "jwk"}
        or header.get("alg") != "ES256"
        or header.get("typ") != OPC_PROOF_TYPE
    ):
        raise OpcProtocolError("OPC proof header is invalid")
    public_jwk = _canonical_public_jwk(header.get("jwk"))
    public_key = _public_key(public_jwk)
    try:
        jwt.decode(
            proof,
            public_key,
            algorithms=["ES256"],
            options={
                "verify_aud": False,
                "verify_exp": False,
                "verify_iat": False,
                "verify_nbf": False,
            },
        )
    except jwt.InvalidTokenError as exc:
        raise OpcProtocolError("OPC proof signature verification failed") from exc
    allowed_claims = {
        "aud",
        "action",
        "installation_id",
        "request_id",
        "iat",
        "exp",
    }
    if checked_action == "pair":
        allowed_claims.add("label")
    required_claims = allowed_claims - {"label"}
    if set(claims) - allowed_claims or not required_claims.issubset(claims):
        raise OpcProtocolError("OPC proof claims are invalid")
    if claims.get("aud") != canonical_origin or claims.get("action") != checked_action:
        raise OpcProtocolError("OPC proof does not match this request")
    _validate_request_id(claims.get("request_id"))
    issued_at = _validate_timestamp(claims.get("iat"), field_name="issued at")
    expires_at = _validate_timestamp(claims.get("exp"), field_name="expiry")
    if expires_at != issued_at + OPC_PROOF_TTL_SECONDS:
        raise OpcProtocolError("OPC proof lifetime is invalid")
    if issued_at > current_time + OPC_MAX_CLOCK_SKEW_SECONDS:
        raise OpcProtocolError("OPC proof is from the future")
    if expires_at < current_time - OPC_MAX_CLOCK_SKEW_SECONDS:
        raise OpcProtocolError("OPC proof has expired")
    expected_installation_id = installation_id(public_jwk)
    if claims.get("installation_id") != expected_installation_id:
        raise OpcProtocolError("OPC proof installation id is invalid")
    if "label" in claims:
        _validate_label(claims["label"])
    return {**claims, "public_jwk": public_jwk}
