from __future__ import annotations

import base64
import binascii
import json
import re
import secrets
import time
from collections.abc import Callable, Mapping
from urllib.parse import quote

import httpx

from .hosted_enrollment import (
    EnrollmentAuthentication,
    EnrollmentRequestNotDispatched,
    _canonical_enrollment_endpoint,
)
from shared.hosted_facilitator_protocol import (
    DeviceSigningKey,
    build_dpop_proof,
    canonical_json_bytes,
)


_MAX_RESPONSE_BYTES = 64 * 1024
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}$")
_TOKEN = re.compile(r"^[\x21-\x7e]{1,8192}$")
_BASE64URL = re.compile(r"^[A-Za-z0-9_-]+$")


class _DuplicateJSONKey(ValueError):
    pass


class EnrollmentTransportError(RuntimeError):
    """An enrollment response cannot be treated as a successful result."""


class EnrollmentTransportConflict(EnrollmentTransportError):
    """The remote endpoint deterministically rejected the request."""

    def __init__(self, status_code: int) -> None:
        if type(status_code) is not int or not 400 <= status_code < 500:
            raise ValueError("enrollment conflict status is invalid")
        self.status_code = status_code
        super().__init__(f"enrollment request rejected with HTTP {status_code}")


class HttpxEnrollmentTransport:
    """Synchronous HTTP transport for the Hosted enrollment lifecycle."""

    def __setattr__(self, name: str, value: object) -> None:
        if name == "_endpoint" and "_endpoint" in self.__dict__:
            raise AttributeError("enrollment endpoint is immutable")
        super().__setattr__(name, value)

    def __init__(
        self,
        endpoint: str,
        *,
        timeout_seconds: float = 10.0,
        max_response_bytes: int = _MAX_RESPONSE_BYTES,
        clock: Callable[[], int] | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._endpoint = _canonical_enrollment_endpoint(endpoint)
        if (
            type(max_response_bytes) is not int
            or max_response_bytes <= 0
            or max_response_bytes > _MAX_RESPONSE_BYTES
        ):
            raise ValueError("enrollment response limit is invalid")
        if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)):
            raise ValueError("enrollment timeout is invalid")
        if timeout_seconds <= 0:
            raise ValueError("enrollment timeout is invalid")
        self._max_response_bytes = max_response_bytes
        self._clock = clock if clock is not None else lambda: int(time.time())
        self.client = httpx.Client(
            timeout=float(timeout_seconds),
            follow_redirects=False,
            transport=transport,
            trust_env=False,
        )

    @property
    def endpoint(self) -> str:
        return self._endpoint

    def close(self) -> None:
        self.client.close()

    def __enter__(self) -> "HttpxEnrollmentTransport":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def enroll(self, request: dict[str, object]) -> dict[str, object]:
        _validate_enrollment_request(request)
        return self._request("POST", self._endpoint, request)

    def prepare_rotation(
        self,
        request: dict[str, object],
        *,
        authentication: EnrollmentAuthentication,
    ) -> dict[str, object]:
        _validate_request_dict(request)
        _validate_authentication_shape(authentication)
        node_id = _request_identifier(request, "node_id")
        rotation_id = _request_identifier(request, "rotation_id")
        url = self._lifecycle_url(node_id, "rotations", rotation_id, "prepare")
        _validate_authenticated_request(
            request,
            authentication,
            expected_epoch_field="expected_epoch",
        )
        return self._request("POST", url, request, authentication=authentication)

    def commit_rotation(
        self,
        request: dict[str, object],
        *,
        authentication: EnrollmentAuthentication,
    ) -> dict[str, object]:
        _validate_request_dict(request)
        _validate_authentication_shape(authentication)
        node_id = _request_identifier(request, "node_id")
        rotation_id = _request_identifier(request, "rotation_id")
        url = self._lifecycle_url(node_id, "rotations", rotation_id, "commit")
        _validate_authenticated_request(
            request,
            authentication,
            expected_epoch_field="next_epoch",
        )
        return self._request("POST", url, request, authentication=authentication)

    def revoke(
        self,
        request: dict[str, object],
        *,
        authentication: EnrollmentAuthentication,
    ) -> dict[str, object]:
        _validate_request_dict(request)
        _validate_authentication_shape(authentication)
        node_id = _request_identifier(request, "node_id")
        revocation_id = _request_identifier(request, "revocation_id")
        url = self._lifecycle_url(node_id, "revocations", revocation_id)
        _validate_authenticated_request(
            request,
            authentication,
            expected_epoch_field="credential_epoch",
        )
        return self._request("DELETE", url, request, authentication=authentication)

    def _lifecycle_url(self, node_id: str, resource: str, identifier: str, suffix: str | None = None) -> str:
        parts = [self._endpoint, quote(node_id, safe=""), resource, quote(identifier, safe="")]
        if suffix is not None:
            parts.append(suffix)
        return "/".join(parts)

    def _request(
        self,
        method: str,
        url: str,
        payload: dict[str, object],
        *,
        authentication: EnrollmentAuthentication | None = None,
    ) -> dict[str, object]:
        if type(method) is not str or method not in {"POST", "DELETE"}:
            raise EnrollmentRequestNotDispatched("enrollment request method is invalid")
        if type(url) is not str or not url:
            raise EnrollmentRequestNotDispatched("enrollment request URL is invalid")
        body = _canonical_request_body(payload)
        headers = {
            "Accept": "application/json",
            "Accept-Encoding": "identity",
            "Content-Type": "application/json",
        }
        if authentication is not None:
            headers.update(_authentication_headers(method, url, authentication, self._clock))
        try:
            request = self.client.build_request(method, url, headers=headers, content=body)
        except Exception as exc:
            raise EnrollmentRequestNotDispatched("enrollment request was not prepared") from exc
        try:
            response = self.client.send(request, stream=True)
        except Exception as exc:
            # Once send() has been called, even a transport exception leaves
            # the remote outcome unknown.  The manager must retain its
            # pending state and replay the exact request.
            raise EnrollmentTransportError("enrollment request outcome is unknown") from exc
        try:
            if 400 <= response.status_code < 500:
                raise EnrollmentTransportConflict(response.status_code)
            if response.status_code >= 500:
                raise EnrollmentTransportError("enrollment service is unavailable")
            expected_status = 201 if method == "POST" and url == self.endpoint else 200
            if response.status_code != expected_status:
                raise EnrollmentTransportError("enrollment response status is unexpected")
            return _decode_response(response, self._max_response_bytes)
        except EnrollmentTransportError:
            raise
        except Exception as exc:
            raise EnrollmentTransportError("enrollment response is invalid") from exc
        finally:
            response.close()


# Keep the protocol name discoverable without making callers depend on an
# implementation-specific spelling.
HostedEnrollmentHttpTransport = HttpxEnrollmentTransport


def _validate_request_dict(request: object) -> None:
    if type(request) is not dict:
        raise EnrollmentRequestNotDispatched("enrollment request body is invalid")


def _validate_enrollment_request(request: object) -> None:
    _validate_request_dict(request)
    token = request.get("token")
    if type(token) is not str or _TOKEN.fullmatch(token) is None:
        raise EnrollmentRequestNotDispatched("enrollment token is invalid")


def _request_identifier(request: Mapping[str, object], field_name: str) -> str:
    _validate_request_dict(request)
    value = request.get(field_name)
    if type(value) is not str or _IDENTIFIER.fullmatch(value) is None:
        raise EnrollmentRequestNotDispatched("enrollment request identity is invalid")
    return value


def _canonical_request_body(payload: object) -> bytes:
    _validate_request_dict(payload)
    try:
        return canonical_json_bytes(payload)
    except Exception as exc:
        raise EnrollmentRequestNotDispatched("enrollment request body is invalid") from exc


def _decode_private_key(encoded: object) -> DeviceSigningKey:
    if type(encoded) is not str or not encoded or _BASE64URL.fullmatch(encoded) is None:
        raise EnrollmentRequestNotDispatched("enrollment authentication is invalid")
    try:
        raw = base64.b64decode(
            encoded + "=" * (-len(encoded) % 4),
            altchars=b"-_",
            validate=True,
        )
    except (ValueError, binascii.Error) as exc:
        raise EnrollmentRequestNotDispatched("enrollment authentication is invalid") from exc
    if base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii") != encoded:
        raise EnrollmentRequestNotDispatched("enrollment authentication is invalid")
    try:
        return DeviceSigningKey.from_pkcs8_der(raw)
    except Exception as exc:
        raise EnrollmentRequestNotDispatched("enrollment authentication is invalid") from exc


def _authentication_headers(
    method: str,
    url: str,
    authentication: EnrollmentAuthentication,
    clock: Callable[[], int],
) -> dict[str, str]:
    _validate_authentication_shape(authentication)
    if not callable(clock):
        raise EnrollmentRequestNotDispatched("enrollment clock is invalid")
    key = _decode_private_key(authentication.private_key_pkcs8_b64)
    try:
        now = clock()
        proof = build_dpop_proof(
            key,
            method=method,
            url=url,
            access_token=authentication.access_token,
            now=now,
            jti=secrets.token_urlsafe(24),
        )
    except Exception as exc:
        raise EnrollmentRequestNotDispatched("enrollment authentication is invalid") from exc
    return {
        "Authorization": f"DPoP {authentication.access_token}",
        "DPoP": proof,
    }


def _validate_authenticated_request(
    request: Mapping[str, object],
    authentication: EnrollmentAuthentication,
    *,
    expected_epoch_field: str,
) -> None:
    _validate_authentication_shape(authentication)
    _validate_request_dict(request)
    _request_identifier(request, "tenant_id")
    _request_identifier(request, "node_id")
    if request["tenant_id"] != authentication.tenant_id or request["node_id"] != authentication.node_id:
        raise EnrollmentRequestNotDispatched("enrollment request identity is invalid")
    epoch = request.get(expected_epoch_field)
    if type(epoch) is not int or epoch != authentication.credential_epoch:
        raise EnrollmentRequestNotDispatched("enrollment request epoch is invalid")


def _validate_authentication_shape(authentication: object) -> None:
    if not isinstance(authentication, EnrollmentAuthentication):
        raise EnrollmentRequestNotDispatched("enrollment authentication is invalid")
    if type(authentication.access_token) is not str or _TOKEN.fullmatch(
        authentication.access_token
    ) is None:
        raise EnrollmentRequestNotDispatched("enrollment authentication is invalid")
    _request_identifier({"tenant_id": authentication.tenant_id}, "tenant_id")
    _request_identifier({"node_id": authentication.node_id}, "node_id")
    if (
        type(authentication.credential_epoch) is not int
        or authentication.credential_epoch <= 0
    ):
        raise EnrollmentRequestNotDispatched("enrollment authentication is invalid")
    _decode_private_key(authentication.private_key_pkcs8_b64)


def _decode_response(response: httpx.Response, max_bytes: int) -> dict[str, object]:
    content_type = response.headers.get("content-type", "")
    media_type = content_type.split(";", 1)[0].strip().lower()
    if media_type != "application/json":
        raise EnrollmentTransportError("enrollment response content type is invalid")
    content_length = response.headers.get("content-length")
    if content_length is not None:
        try:
            declared = int(content_length)
        except ValueError as exc:
            raise EnrollmentTransportError("enrollment response size is invalid") from exc
        if declared < 0 or declared > max_bytes:
            raise EnrollmentTransportError("enrollment response is too large")
    try:
        if response.is_stream_consumed:
            raw = response.content
            if len(raw) > max_bytes:
                raise EnrollmentTransportError("enrollment response is too large")
        else:
            chunks: list[bytes] = []
            size = 0
            for chunk in response.iter_raw():
                size += len(chunk)
                if size > max_bytes:
                    raise EnrollmentTransportError("enrollment response is too large")
                chunks.append(chunk)
            raw = b"".join(chunks)
    except EnrollmentTransportError:
        raise
    except Exception as exc:
        raise EnrollmentTransportError("enrollment response could not be read") from exc
    try:
        decoded = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_json_keys,
        )
    except (_DuplicateJSONKey, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise EnrollmentTransportError("enrollment response is invalid JSON") from exc
    if not isinstance(decoded, dict):
        raise EnrollmentTransportError("enrollment response must be an object")
    return decoded


def _reject_duplicate_json_keys(pairs: list[tuple[object, object]]) -> dict[object, object]:
    result: dict[object, object] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJSONKey("duplicate JSON object key")
        result[key] = value
    return result
