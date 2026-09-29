from __future__ import annotations

import base64
import binascii
import json
import re
from collections.abc import Callable
from typing import Any

import anyio
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from config import FacilitatorConfig
from authority import (
    CoreAuthorityRejected,
    CoreAuthorityResolver,
    CoreAuthorityUnavailable,
)
from enrollment import EnrollmentError, EnrollmentService
from execution_models import ExecutionIntent, ExecutionState, HostedExecution
from execution_repository import ExecutionConflict, ExecutionRepository
from pilot_gate import PilotGateDenied
from models import NodeRegistration, PreflightRecord, ResponseSigner
from relayer import HostedRelayer, RelayerExecutionError
from replay import ReplayCoordinator, ReplayUnavailable, RedisReplayCoordinator
from repository import (
    ControlPlaneRepository,
    PostgresRepository,
    RepositoryConflict,
    RepositoryUnavailable,
    digest_secret,
)
from shared.hosted_facilitator_protocol import (
    HostedPaymentEnvelope,
    HostedExecutionResponse,
    HostedPreflightResponse,
    HostedProtocolError,
    HostedRevertReleaseEvidence,
    MAX_DPOP_AGE_SECONDS,
    UNSIGNED_EXECUTION_EXPIRED,
    verify_dpop_proof,
    verify_payment_envelope,
)


_AUTHORIZATION = re.compile(r"^DPoP ([\x21-\x2b\x2d-\x7e]{1,8192})$")
_MAX_AUTHORIZATION_BYTES = 8192
_MAX_DPOP_PROOF_BYTES = 64 * 1024
_PREFLIGHT_PATH = "/v1/preflight"
_EXECUTION_PATH = "/v1/executions"
_EXECUTION_LOOKUP_PATH = "/v1/execution-lookups"
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}$")
_BASE64URL = re.compile(r"^[A-Za-z0-9_-]+$")
_AUTHORITY_THREAD_LIMITER = anyio.CapacityLimiter(8)


class _ApiFailure(Exception):
    def __init__(self, status: int, code: str, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.code = code
        self.detail = detail


class _DuplicateJSONKey(ValueError):
    pass


def _duplicate_rejecting_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJSONKey(key)
        result[key] = value
    return result


def _error(failure: _ApiFailure) -> JSONResponse:
    return JSONResponse(
        {"code": failure.code, "status": failure.status, "detail": failure.detail},
        status_code=failure.status,
        headers={"cache-control": "no-store"},
    )


def _validate_expected_epoch(value: object) -> int:
    if type(value) is not int or value <= 0:
        raise _ApiFailure(400, "invalid_body", "credential epoch is invalid")
    return value


def _path_identifier(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise _ApiFailure(404, "execution_not_found", "execution not found")
    return value


async def _read_json(request: Request, *, max_bytes: int) -> dict[str, Any]:
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            declared = int(content_length)
        except ValueError as exc:
            raise _ApiFailure(400, "invalid_body", "request body is invalid") from exc
        if declared < 0:
            raise _ApiFailure(400, "invalid_body", "request body is invalid")
        if declared > max_bytes:
            raise _ApiFailure(413, "body_too_large", "request body is too large")
    raw = await request.body()
    if len(raw) > max_bytes:
        raise _ApiFailure(413, "body_too_large", "request body is too large")
    try:
        payload = json.loads(
            raw.decode("utf-8"), object_pairs_hook=_duplicate_rejecting_object
        )
    except (_DuplicateJSONKey, UnicodeDecodeError, ValueError, TypeError) as exc:
        raise _ApiFailure(400, "invalid_body", "request body is invalid") from exc
    if not isinstance(payload, dict):
        raise _ApiFailure(400, "invalid_body", "request body is invalid")
    return payload


def _require_fields(payload: dict[str, Any], expected: set[str]) -> None:
    if set(payload) != expected:
        raise _ApiFailure(400, "invalid_body", "request body fields are invalid")


def _auth_token(request: Request) -> str:
    value = request.headers.get("authorization")
    if value is None:
        raise _ApiFailure(401, "invalid_authentication", "authentication failed")
    try:
        encoded = value.encode("ascii")
    except UnicodeEncodeError as exc:
        raise _ApiFailure(
            401, "invalid_authentication", "authentication failed"
        ) from exc
    if len(encoded) > _MAX_AUTHORIZATION_BYTES:
        raise _ApiFailure(401, "invalid_authentication", "authentication failed")
    match = _AUTHORIZATION.fullmatch(value)
    if match is None:
        raise _ApiFailure(401, "invalid_authentication", "authentication failed")
    return match.group(1)


def _dpop_header(request: Request) -> str:
    value = request.headers.get("dpop")
    if value is None:
        raise _ApiFailure(401, "invalid_authentication", "authentication failed")
    try:
        encoded = value.encode("ascii")
    except UnicodeEncodeError as exc:
        raise _ApiFailure(
            401, "invalid_authentication", "authentication failed"
        ) from exc
    if len(encoded) > _MAX_DPOP_PROOF_BYTES:
        raise _ApiFailure(401, "invalid_authentication", "authentication failed")
    return value


def _digest_text(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _digest_from_payload(payload: dict[str, Any]) -> bytes | None:
    value = payload.get("access_token_digest")
    if not isinstance(value, str) or _BASE64URL.fullmatch(value) is None:
        return None
    try:
        decoded = base64.b64decode(
            value + "=" * (-len(value) % 4),
            altchars=b"-_",
            validate=True,
        )
    except (ValueError, TypeError, binascii.Error):
        return None
    if len(decoded) != 32 or _digest_text(decoded) != value:
        return None
    return decoded


def _enrollment_payload(result: NodeRegistration) -> dict[str, Any]:
    return {
        "tenant_id": result.tenant_id,
        "node_id": result.node_id,
        "wallet_binding_id": result.wallet_binding_id,
        "expected_epoch": 0,
        "next_epoch": 1,
        "credential_epoch": result.credential_epoch,
        "device_key_id": result.device_key_id,
        "access_token_digest": _digest_text(result.access_token_digest),
        "status": result.status,
    }


def _rotation_payload(
    request: dict[str, Any],
    *,
    status: str,
    credential_epoch: int | None = None,
) -> dict[str, Any]:
    response = {
        "rotation_id": request["rotation_id"],
        "tenant_id": request["tenant_id"],
        "node_id": request["node_id"],
        "wallet_binding_id": request["wallet_binding_id"],
        "expected_epoch": request["expected_epoch"],
        "next_epoch": request["next_epoch"],
        "device_key_id": request["device_key_id"],
        "access_token_digest": request["access_token_digest"],
        "status": status,
    }
    if credential_epoch is not None:
        response["credential_epoch"] = credential_epoch
    return response


def _revocation_payload(
    request: dict[str, Any],
    *,
    credential_epoch: int,
) -> dict[str, Any]:
    return {
        "revocation_id": request["revocation_id"],
        "tenant_id": request["tenant_id"],
        "node_id": request["node_id"],
        "wallet_binding_id": request["wallet_binding_id"],
        "expected_epoch": request["expected_epoch"],
        "next_epoch": request["next_epoch"],
        "credential_epoch": credential_epoch,
        "device_key_id": request["device_key_id"],
        "access_token_digest": request["access_token_digest"],
        "status": "revoked",
    }


def _node_scope(node: NodeRegistration, envelope: HostedPaymentEnvelope) -> None:
    if envelope.tenant_id != node.tenant_id:
        raise _ApiFailure(403, "scope_mismatch", "payment scope is invalid")
    if envelope.node_id != node.node_id:
        raise _ApiFailure(403, "scope_mismatch", "payment scope is invalid")
    if envelope.wallet_binding_id != node.wallet_binding_id:
        raise _ApiFailure(403, "scope_mismatch", "payment scope is invalid")


def _execution_scope(
    node: NodeRegistration,
    envelope: HostedPaymentEnvelope,
    intent: ExecutionIntent,
) -> None:
    _node_scope(node, envelope)
    expected = {
        "tenant_id": envelope.tenant_id,
        "node_id": envelope.node_id,
        "wallet_binding_id": envelope.wallet_binding_id,
        "capability_id": envelope.payment_capability_id,
        "reservation_id": envelope.reservation_id,
        "purchase_id": envelope.purchase_id,
        "request_id": envelope.request_id,
        "request_hash": envelope.request_hash,
        "idempotency_key": envelope.idempotency_key,
        "chain": envelope.chain_id,
        "owner": envelope.wallet_address,
        "payee": envelope.pay_to,
        "token": envelope.asset_contract,
        "amount_atomic": envelope.amount_atomic,
        "executor": envelope.executor_contract,
        "owner_nonce": int(envelope.request_nonce, 16),
        "deadline": envelope.expires_at,
        "capability_hash": envelope.payment_capability_hash,
        "reservation_hash": envelope.reservation_hash,
        "execution_scope_hash": envelope.execution_scope_hash,
    }
    if any(getattr(intent, key) != value for key, value in expected.items()):
        raise _ApiFailure(403, "scope_mismatch", "Core execution scope is invalid")


def _unsigned_expiry_timestamp(execution: HostedExecution) -> int | None:
    state = ExecutionState(execution.status)
    if state not in {ExecutionState.EXPIRED, ExecutionState.RELEASED}:
        return None
    # A released execution with raw transaction material follows the existing
    # on-chain revert-release path.  Every other expired/released terminal row
    # must prove that no signing or broadcast material ever existed.
    if state is ExecutionState.RELEASED and execution.raw_transaction_hash is not None:
        return None

    for field_name, value in (
        ("signature", execution.signature),
        ("raw_transaction", execution.raw_transaction),
        ("raw_transaction_hash", execution.raw_transaction_hash),
        ("unsigned_transaction_hash", execution.unsigned_transaction_hash),
        ("broadcast_attempts", execution.broadcast_attempts),
        ("broadcasted_at", execution.broadcasted_at),
        ("signing_claim_expires_at", execution.signing_claim_expires_at),
        ("receipt_status", execution.receipt_status),
        ("receipt_block_number", execution.receipt_block_number),
        ("receipt_block_hash", execution.receipt_block_hash),
        ("confirmations", execution.confirmations),
        ("safe_block_number", execution.safe_block_number),
        ("safe_block_hash", execution.safe_block_hash),
        ("watcher_version", execution.watcher_version),
        ("finality_boundary", execution.finality_boundary),
        ("confirmed_at", execution.confirmed_at),
        ("finalized_at", execution.finalized_at),
        ("reverted_at", execution.reverted_at),
        ("reorg_state", execution.reorg_state if execution.reorg_state != "none" else None),
        ("reorg_evidence", execution.reorg_evidence),
        ("reorg_reviewed_at", execution.reorg_reviewed_at),
        ("release_evidence", execution.release_evidence),
    ):
        if value is not None and not (
            field_name in {"broadcast_attempts", "confirmations"} and value == 0
        ):
            raise ExecutionConflict(
                "unsigned expiry attestation contains durable " + field_name
            )

    terminal_at = (
        execution.expired_at
        if state is ExecutionState.EXPIRED
        else execution.released_at
    )
    if terminal_at is None:
        raise ExecutionConflict("unsigned expiry attestation lacks terminal timestamp")
    if terminal_at < execution.deadline:
        raise ExecutionConflict(
            "unsigned expiry attestation terminal timestamp precedes deadline"
        )
    if terminal_at < execution.created_at:
        raise ExecutionConflict(
            "unsigned expiry attestation terminal timestamp precedes issued_at"
        )
    if (
        execution.expired_at is not None
        and execution.expired_at != terminal_at
    ):
        raise ExecutionConflict(
            "unsigned expiry attestation expired_at conflicts with terminal timestamp"
        )
    if (
        execution.released_at is not None
        and execution.released_at != terminal_at
    ):
        raise ExecutionConflict(
            "unsigned expiry attestation released_at conflicts with terminal timestamp"
        )
    return terminal_at


def _execution_projection(
    execution: HostedExecution,
    *,
    server_key_id: str,
) -> HostedExecutionResponse:
    state = ExecutionState(execution.status)
    unsigned_expiry_at = _unsigned_expiry_timestamp(execution)
    if state in {
        ExecutionState.PREFLIGHT_APPROVED,
        ExecutionState.SIGNING,
        ExecutionState.SIGNED,
    }:
        public_state = "preparing"
    elif unsigned_expiry_at is not None:
        public_state = "expired"
    else:
        public_state = state.value
    failure_reason = None
    if unsigned_expiry_at is not None:
        failure_reason = UNSIGNED_EXECUTION_EXPIRED
    elif state is ExecutionState.SUBMISSION_REJECTED:
        failure_reason = (execution.submission_failure_code or "submission_rejected").upper()
    elif state is ExecutionState.RELEASED:
        failure_reason = (
            "SAFE_REVERT_RELEASE"
            if execution.raw_transaction_hash is not None
            else (execution.submission_failure_code or "authorization_expired").upper()
        )
    elif state is ExecutionState.EXPIRED:
        failure_reason = "AUTHORIZATION_EXPIRED"
    elif state is ExecutionState.REVERTED:
        failure_reason = "ONCHAIN_REVERT"
    elif state is ExecutionState.REORG_REVIEW:
        failure_reason = "REORG_DETECTED"
    transaction_hash = execution.raw_transaction_hash
    submitted_at = execution.broadcasted_at
    if public_state in {"preparing", "expired", "rejected"}:
        transaction_hash = None
        submitted_at = None
    release_evidence = None
    if state is ExecutionState.RELEASED and execution.raw_transaction_hash is not None:
        release_evidence = HostedRevertReleaseEvidence.model_validate(
            execution.release_evidence,
            strict=True,
        )
    return HostedExecutionResponse(
        request_id=execution.request_id,
        request_hash=execution.request_hash,
        idempotency_key=execution.idempotency_key,
        execution_id=execution.execution_id,
        capability_id=execution.capability_id,
        capability_hash=execution.capability_hash,
        reservation_id=execution.reservation_id,
        reservation_hash=execution.reservation_hash,
        purchase_id=execution.purchase_id,
        execution_scope_hash=execution.execution_scope_hash,
        owner=execution.owner,
        payee=execution.payee,
        token=execution.token,
        amount_atomic=execution.amount_atomic,
        executor=execution.executor,
        signer_epoch=execution.signer_epoch,
        owner_nonce=f"0x{execution.owner_nonce:064x}",
        deadline=execution.deadline,
        state=public_state,
        transaction_hash=transaction_hash,
        receipt_block_hash=execution.receipt_block_hash,
        receipt_block_number=execution.receipt_block_number,
        safe_block_hash=execution.safe_block_hash,
        safe_block_number=execution.safe_block_number,
        confirmations=execution.confirmations,
        failure_reason_code=failure_reason,
        issued_at=execution.created_at,
        submitted_at=submitted_at,
        confirmed_at=execution.confirmed_at,
        finalized_at=execution.finalized_at,
        reverted_at=execution.reverted_at,
        reorg_reviewed_at=execution.reorg_reviewed_at,
        released_at=execution.released_at,
        expired_at=(
            unsigned_expiry_at
            if unsigned_expiry_at is not None
            else execution.expired_at
            if execution.expired_at is not None
            else execution.released_at if public_state == "expired" else None
        ),
        watcher_version=getattr(execution, "watcher_version", None),
        chain_id=execution.chain,
        finality_boundary=getattr(execution, "finality_boundary", None),
        release_evidence=release_evidence,
        server_key_id=server_key_id,
    )


_DURABLE_EXECUTION_REPLAY_STATES = frozenset(
    {
        ExecutionState.SUBMITTED,
        ExecutionState.SUBMISSION_UNKNOWN,
        ExecutionState.SUBMISSION_REJECTED,
        ExecutionState.CONFIRMED,
        ExecutionState.FINALIZED,
        ExecutionState.REVERTED,
        ExecutionState.EXPIRED,
        ExecutionState.RELEASED,
        ExecutionState.REORG_REVIEW,
    }
)


def _configured_chain_token(config: FacilitatorConfig) -> tuple[str, str]:
    return config.chain, config.asset_contract


def _conflict_failure(exc: RepositoryConflict) -> _ApiFailure:
    detail = str(exc).lower()
    if "idempotency" in detail:
        code = "idempotency_conflict"
    elif "request id" in detail:
        code = "request_id_conflict"
    elif "request nonce" in detail:
        code = "request_nonce_conflict"
    elif "capability" in detail:
        code = "capability_conflict"
    elif "reservation" in detail:
        code = "reservation_conflict"
    elif "replay" in detail:
        code = "dpop_replay"
    else:
        code = "conflict"
    return _ApiFailure(409, code, "request conflicts with existing state")


def create_app(
    config: FacilitatorConfig,
    *,
    repository: ControlPlaneRepository,
    replay: ReplayCoordinator,
    response_signer: ResponseSigner,
    clock: Callable[[], int],
    execution_repository: ExecutionRepository | None = None,
    execution_service: Any | None = None,
    intent_resolver: Any | None = None,
) -> FastAPI:
    """Build the Hosted control-plane API with all stateful dependencies explicit."""
    if not isinstance(config, FacilitatorConfig):
        raise TypeError("facilitator config is required")
    if config.environment == "production":
        if not isinstance(repository, PostgresRepository):
            raise ValueError("production facilitator requires PostgreSQL repository")
        # Production construction must use the durable SET NX EX adapter; test
        # fakes are accepted only under the explicit test environment.
        if not isinstance(replay, RedisReplayCoordinator):
            raise ValueError("production facilitator requires Redis replay coordinator")
        if not isinstance(execution_repository, ExecutionRepository):
            raise ValueError("production facilitator requires execution repository")
        if not isinstance(execution_service, HostedRelayer):
            raise ValueError("production facilitator requires Hosted relayer")
        if execution_repository.pilot_policy is None:
            raise ValueError("production facilitator requires PilotGate policy")
        if execution_service.execution_repository is not execution_repository:
            raise ValueError(
                "production facilitator requires shared execution repository"
            )
        if not isinstance(intent_resolver, CoreAuthorityResolver):
            raise ValueError("production facilitator requires Core authority resolver")
        if not callable(getattr(intent_resolver, "preflight", None)):
            raise ValueError("production facilitator requires preflight authority resolver")
        if execution_service.approval_verifier is not intent_resolver:
            raise ValueError("production facilitator requires shared Core authority verifier")
    service = EnrollmentService(
        repository=repository,
        enrollment_ttl_seconds=config.enrollment_ttl_seconds,
        clock=clock,
    )
    app = FastAPI(title="Clink Hosted Facilitator", docs_url=None, redoc_url=None)
    app.state.enrollment_service = service
    app.state.config = config

    async def _authenticate_credential(
        request: Request,
        *,
        expected_path: str,
        token: str,
        node: NodeRegistration,
        credential_epoch: int,
        trusted_public_jwk: dict[str, str],
    ) -> tuple[str, NodeRegistration, Any]:
        dpop = _dpop_header(request)
        expected_url = f"{config.public_origin}{expected_path}"
        now = _clock_now(clock)
        try:
            claims = verify_dpop_proof(
                dpop,
                trusted_public_jwk=trusted_public_jwk,
                method=request.method,
                url=expected_url,
                access_token=token,
                now=now,
            )
        except (HostedProtocolError, ValueError) as exc:
            raise _ApiFailure(401, "invalid_authentication", "authentication failed") from exc
        replay_expires_at = max(
            now + config.dpop_ttl_seconds,
            claims.iat + MAX_DPOP_AGE_SECONDS + 1,
        )
        replay_ttl_seconds = replay_expires_at - now
        try:
            accepted = replay.consume_dpop_jti(
                tenant_id=node.tenant_id,
                node_id=node.node_id,
                credential_epoch=credential_epoch,
                jti=claims.jti,
                ttl_seconds=replay_ttl_seconds,
            )
        except ReplayUnavailable as exc:
            raise _ApiFailure(503, "replay_unavailable", "service unavailable") from exc
        except Exception as exc:
            raise _ApiFailure(503, "replay_unavailable", "service unavailable") from exc
        if not accepted:
            raise _ApiFailure(401, "dpop_replay", "authentication failed")
        try:
            accepted_durable = repository.consume_dpop_jti(
                tenant_id=node.tenant_id,
                node_id=node.node_id,
                credential_epoch=credential_epoch,
                jti=claims.jti,
                expires_at=replay_expires_at,
                now=now,
            )
        except RepositoryConflict as exc:
            raise _ApiFailure(401, "dpop_replay", "authentication failed") from exc
        except RepositoryUnavailable as exc:
            raise _ApiFailure(503, "dependency_unavailable", "service unavailable") from exc
        except Exception as exc:
            raise _ApiFailure(503, "dependency_unavailable", "service unavailable") from exc
        if not accepted_durable:
            raise _ApiFailure(401, "dpop_replay", "authentication failed")
        return token, node, claims

    async def authenticate(
        request: Request,
        *,
        expected_path: str,
        expected_node_id: str | None = None,
    ) -> tuple[str, NodeRegistration, Any]:
        token = _auth_token(request)
        try:
            node = repository.get_node_by_access_digest(digest_secret(token))
        except RepositoryUnavailable as exc:
            raise _ApiFailure(503, "dependency_unavailable", "service unavailable") from exc
        except Exception as exc:
            raise _ApiFailure(401, "invalid_authentication", "authentication failed") from exc
        if node is None or node.status != "active":
            raise _ApiFailure(401, "invalid_authentication", "authentication failed")
        if expected_node_id is not None and node.node_id != expected_node_id:
            raise _ApiFailure(403, "scope_mismatch", "node scope is invalid")
        return await _authenticate_credential(
            request,
            expected_path=expected_path,
            token=token,
            node=node,
            credential_epoch=node.credential_epoch,
            trusted_public_jwk=node.device_public_jwk,
        )

    def _lifecycle_identifier(value: object, *, field_name: str) -> str:
        if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
            raise _ApiFailure(400, "invalid_body", "request body fields are invalid")
        return value

    def _lifecycle_epoch(value: object, *, field_name: str) -> int:
        if type(value) is not int or value <= 0:
            raise _ApiFailure(400, "invalid_body", "request body fields are invalid")
        return value

    async def authenticate_commit(
        request: Request,
        *,
        expected_path: str,
        expected_node_id: str,
        payload: dict[str, Any],
    ) -> tuple[str, NodeRegistration, Any]:
        token = _auth_token(request)
        tenant_id = _lifecycle_identifier(payload.get("tenant_id"), field_name="tenant_id")
        node_id = _lifecycle_identifier(payload.get("node_id"), field_name="node_id")
        rotation_id = _lifecycle_identifier(
            payload.get("rotation_id"), field_name="rotation_id"
        )
        if node_id != expected_node_id:
            raise _ApiFailure(404, "enrollment_not_found", "enrollment not found")
        if expected_path.rsplit("/", 2)[-2] != rotation_id:
            raise _ApiFailure(404, "enrollment_not_found", "enrollment not found")
        try:
            pending = repository.get_pending_rotation_by_access_digest(
                digest_secret(token),
                tenant_id=tenant_id,
                node_id=node_id,
            )
        except RepositoryUnavailable as exc:
            raise _ApiFailure(503, "dependency_unavailable", "service unavailable") from exc
        except Exception as exc:
            raise _ApiFailure(503, "dependency_unavailable", "service unavailable") from exc
        if pending is not None:
            if pending.rotation_id != rotation_id:
                raise _ApiFailure(401, "invalid_authentication", "authentication failed")
            try:
                node = repository.get_node(tenant_id, node_id)
            except RepositoryUnavailable as exc:
                raise _ApiFailure(503, "dependency_unavailable", "service unavailable") from exc
            except Exception as exc:
                raise _ApiFailure(503, "dependency_unavailable", "service unavailable") from exc
            if node is None or node.status != "active":
                raise _ApiFailure(401, "invalid_authentication", "authentication failed")
            return await _authenticate_credential(
                request,
                expected_path=expected_path,
                token=token,
                node=node,
                credential_epoch=pending.next_epoch,
                trusted_public_jwk=pending.pending_public_jwk,
            )
        # Once commit succeeds, only the newly active credential can retry the
        # exact commit route.  Do not fall back to the old active credential:
        # before commit it is still valid for normal traffic, but it must not
        # be able to authorize the state transition itself.
        try:
            active = repository.get_node_by_access_digest(digest_secret(token))
        except RepositoryUnavailable as exc:
            raise _ApiFailure(503, "dependency_unavailable", "service unavailable") from exc
        except Exception as exc:
            raise _ApiFailure(503, "dependency_unavailable", "service unavailable") from exc
        if (
            active is None
            or active.status != "active"
            or active.node_id != expected_node_id
            or active.tenant_id != tenant_id
            or type(payload.get("expected_epoch")) is not int
            or type(payload.get("next_epoch")) is not int
            or active.credential_epoch != payload["next_epoch"]
            or active.wallet_binding_id != payload.get("wallet_binding_id")
            or active.device_public_jwk != payload.get("public_jwk")
            or active.device_key_id != payload.get("device_key_id")
            or active.access_token_digest != _digest_from_payload(payload)
        ):
            raise _ApiFailure(401, "invalid_authentication", "authentication failed")
        return await _authenticate_credential(
            request,
            expected_path=expected_path,
            token=token,
            node=active,
            credential_epoch=active.credential_epoch,
            trusted_public_jwk=active.device_public_jwk,
        )

    async def authenticate_revocation(
        request: Request,
        *,
        expected_path: str,
        expected_node_id: str,
        payload: dict[str, Any],
    ) -> tuple[str, NodeRegistration, Any]:
        token = _auth_token(request)
        tenant_id = _lifecycle_identifier(payload.get("tenant_id"), field_name="tenant_id")
        node_id = _lifecycle_identifier(payload.get("node_id"), field_name="node_id")
        revocation_id = _lifecycle_identifier(
            payload.get("revocation_id"), field_name="revocation_id"
        )
        credential_epoch = _lifecycle_epoch(
            payload.get("credential_epoch"), field_name="credential_epoch"
        )
        expected_epoch = _lifecycle_epoch(
            payload.get("expected_epoch"), field_name="expected_epoch"
        )
        if node_id != expected_node_id or credential_epoch != expected_epoch:
            raise _ApiFailure(404, "enrollment_not_found", "enrollment not found")
        if expected_path.rsplit("/", 1)[-1] != revocation_id:
            raise _ApiFailure(404, "enrollment_not_found", "enrollment not found")
        access_digest = digest_secret(token)
        try:
            active = repository.get_node_by_access_digest(access_digest)
        except RepositoryUnavailable as exc:
            raise _ApiFailure(503, "dependency_unavailable", "service unavailable") from exc
        except Exception as exc:
            raise _ApiFailure(503, "dependency_unavailable", "service unavailable") from exc
        if active is not None:
            if active.node_id != node_id or active.tenant_id != tenant_id:
                raise _ApiFailure(403, "scope_mismatch", "node scope is invalid")
            return await _authenticate_credential(
                request,
                expected_path=expected_path,
                token=token,
                node=active,
                credential_epoch=active.credential_epoch,
                trusted_public_jwk=active.device_public_jwk,
            )
        try:
            revoked = repository.get_revoked_node_by_access_digest(
                access_digest,
                tenant_id=tenant_id,
                node_id=node_id,
                revocation_id=revocation_id,
                expected_epoch=expected_epoch,
            )
        except RepositoryUnavailable as exc:
            raise _ApiFailure(503, "dependency_unavailable", "service unavailable") from exc
        except Exception as exc:
            raise _ApiFailure(503, "dependency_unavailable", "service unavailable") from exc
        if revoked is None:
            raise _ApiFailure(401, "invalid_authentication", "authentication failed")
        return await _authenticate_credential(
            request,
            expected_path=expected_path,
            token=token,
            node=revoked,
            credential_epoch=credential_epoch,
            trusted_public_jwk=revoked.device_public_jwk,
        )

    @app.exception_handler(_ApiFailure)
    async def api_failure_handler(_: Request, exc: _ApiFailure) -> JSONResponse:
        return _error(exc)

    @app.post("/v1/enrollments", status_code=201)
    async def enroll(request: Request) -> JSONResponse:
        payload = await _read_json(request, max_bytes=config.max_request_body_bytes)
        _require_fields(
            payload,
            {
                "token",
                "wallet_binding_id",
                "expected_epoch",
                "next_epoch",
                "public_jwk",
                "device_key_id",
                "access_token_digest",
                "status",
            },
        )
        try:
            result = service.enroll(
                payload["token"],
                public_jwk=payload["public_jwk"],
                wallet_binding_id=payload["wallet_binding_id"],
                expected_epoch=payload["expected_epoch"],
                next_epoch=payload["next_epoch"],
                device_key_id=payload["device_key_id"],
                access_token_digest=payload["access_token_digest"],
                status=payload["status"],
            )
        except EnrollmentError as exc:
            raise _ApiFailure(400, "enrollment_failed", "enrollment request is invalid") from exc
        except RepositoryUnavailable as exc:
            raise _ApiFailure(503, "dependency_unavailable", "service unavailable") from exc
        return JSONResponse(
            _enrollment_payload(result),
            status_code=201,
            headers={"cache-control": "no-store"},
        )

    @app.post("/v1/enrollments/{node_id}/rotations/{rotation_id}/prepare")
    async def prepare_rotation(
        request: Request,
        node_id: str,
        rotation_id: str,
    ) -> JSONResponse:
        node_id = _path_identifier(node_id, field_name="node_id")
        rotation_id = _path_identifier(rotation_id, field_name="rotation_id")
        path = f"/v1/enrollments/{node_id}/rotations/{rotation_id}/prepare"
        payload = await _read_json(request, max_bytes=config.max_request_body_bytes)
        _require_fields(
            payload,
            {
                "rotation_id",
                "tenant_id",
                "node_id",
                "wallet_binding_id",
                "expected_epoch",
                "next_epoch",
                "public_jwk",
                "device_key_id",
                "access_token_digest",
            },
        )
        if payload["node_id"] != node_id or payload["rotation_id"] != rotation_id:
            raise _ApiFailure(404, "enrollment_not_found", "enrollment not found")
        _, node, _ = await authenticate(
            request,
            expected_path=path,
            expected_node_id=node_id,
        )
        if (
            payload["tenant_id"] != node.tenant_id
            or payload["wallet_binding_id"] != node.wallet_binding_id
            or payload["expected_epoch"] != node.credential_epoch
        ):
            raise _ApiFailure(
                403,
                "scope_mismatch",
                "node scope is invalid",
            )
        try:
            result = service.prepare_rotation(
                rotation_id=payload["rotation_id"],
                tenant_id=payload["tenant_id"],
                node_id=payload["node_id"],
                wallet_binding_id=payload["wallet_binding_id"],
                expected_epoch=payload["expected_epoch"],
                next_epoch=payload["next_epoch"],
                public_jwk=payload["public_jwk"],
                device_key_id=payload["device_key_id"],
                access_token_digest=payload["access_token_digest"],
            )
        except EnrollmentError as exc:
            raise _ApiFailure(409, "credential_conflict", "credential rotation failed") from exc
        except RepositoryUnavailable as exc:
            raise _ApiFailure(503, "dependency_unavailable", "service unavailable") from exc
        return JSONResponse(
            _rotation_payload(payload, status=result.status),
            headers={"cache-control": "no-store"},
        )

    @app.post("/v1/enrollments/{node_id}/rotations/{rotation_id}/commit")
    async def commit_rotation(
        request: Request,
        node_id: str,
        rotation_id: str,
    ) -> JSONResponse:
        node_id = _path_identifier(node_id, field_name="node_id")
        rotation_id = _path_identifier(rotation_id, field_name="rotation_id")
        path = f"/v1/enrollments/{node_id}/rotations/{rotation_id}/commit"
        payload = await _read_json(request, max_bytes=config.max_request_body_bytes)
        _require_fields(
            payload,
            {
                "rotation_id",
                "tenant_id",
                "node_id",
                "wallet_binding_id",
                "expected_epoch",
                "next_epoch",
                "public_jwk",
                "device_key_id",
                "access_token_digest",
            },
        )
        if payload["node_id"] != node_id or payload["rotation_id"] != rotation_id:
            raise _ApiFailure(404, "enrollment_not_found", "enrollment not found")
        await authenticate_commit(
            request,
            expected_path=path,
            expected_node_id=node_id,
            payload=payload,
        )
        try:
            result = service.commit_rotation(
                rotation_id=payload["rotation_id"],
                tenant_id=payload["tenant_id"],
                node_id=payload["node_id"],
                wallet_binding_id=payload["wallet_binding_id"],
                expected_epoch=payload["expected_epoch"],
                next_epoch=payload["next_epoch"],
                public_jwk=payload["public_jwk"],
                device_key_id=payload["device_key_id"],
                access_token_digest=payload["access_token_digest"],
            )
        except EnrollmentError as exc:
            raise _ApiFailure(409, "credential_conflict", "credential rotation failed") from exc
        except RepositoryUnavailable as exc:
            raise _ApiFailure(503, "dependency_unavailable", "service unavailable") from exc
        return JSONResponse(
            _rotation_payload(
                payload,
                status=result.status,
                credential_epoch=result.credential_epoch,
            ),
            headers={"cache-control": "no-store"},
        )

    @app.delete("/v1/enrollments/{node_id}/revocations/{revocation_id}")
    async def revoke(
        request: Request,
        node_id: str,
        revocation_id: str,
    ) -> JSONResponse:
        node_id = _path_identifier(node_id, field_name="node_id")
        revocation_id = _path_identifier(revocation_id, field_name="revocation_id")
        path = f"/v1/enrollments/{node_id}/revocations/{revocation_id}"
        payload = await _read_json(request, max_bytes=config.max_request_body_bytes)
        _require_fields(
            payload,
            {
                "revocation_id",
                "tenant_id",
                "node_id",
                "wallet_binding_id",
                "credential_epoch",
                "expected_epoch",
                "next_epoch",
                "device_key_id",
                "access_token_digest",
                "status",
            },
        )
        if payload["node_id"] != node_id or payload["revocation_id"] != revocation_id:
            raise _ApiFailure(404, "enrollment_not_found", "enrollment not found")
        await authenticate_revocation(
            request,
            expected_path=path,
            expected_node_id=node_id,
            payload=payload,
        )
        try:
            revoked = service.revoke(
                revocation_id=payload["revocation_id"],
                tenant_id=payload["tenant_id"],
                node_id=payload["node_id"],
                wallet_binding_id=payload["wallet_binding_id"],
                credential_epoch=payload["credential_epoch"],
                expected_epoch=payload["expected_epoch"],
                next_epoch=payload["next_epoch"],
                device_key_id=payload["device_key_id"],
                access_token_digest=payload["access_token_digest"],
                status=payload["status"],
            )
        except EnrollmentError as exc:
            raise _ApiFailure(409, "credential_conflict", "credential revocation failed") from exc
        except RepositoryUnavailable as exc:
            raise _ApiFailure(503, "dependency_unavailable", "service unavailable") from exc
        return JSONResponse(
            _revocation_payload(payload, credential_epoch=revoked.credential_epoch),
            headers={"cache-control": "no-store"},
        )

    @app.post("/v1/preflight")
    async def preflight(request: Request) -> JSONResponse:
        _, node, _ = await authenticate(request, expected_path=_PREFLIGHT_PATH)
        payload = await _read_json(request, max_bytes=config.max_request_body_bytes)
        _require_fields(payload, {"payment_jws"})
        payment_jws = payload["payment_jws"]
        if not isinstance(payment_jws, str) or len(payment_jws.encode("utf-8")) > _MAX_DPOP_PROOF_BYTES:
            raise _ApiFailure(400, "invalid_payment", "payment envelope is invalid")
        try:
            envelope = verify_payment_envelope(
                payment_jws,
                node.device_public_jwk,
                now=_clock_now(clock),
            )
        except (HostedProtocolError, ValueError) as exc:
            raise _ApiFailure(400, "invalid_payment", "payment envelope is invalid") from exc
        if envelope.http_path != _PREFLIGHT_PATH or envelope.http_method != "POST":
            raise _ApiFailure(403, "scope_mismatch", "payment scope is invalid")
        configured_chain, configured_token = _configured_chain_token(config)
        if envelope.chain_id != configured_chain or envelope.asset_contract != configured_token:
            raise _ApiFailure(403, "scope_mismatch", "payment scope is invalid")
        _node_scope(node, envelope)
        if execution_repository is not None:
            try:
                await anyio.to_thread.run_sync(
                    lambda: execution_repository.assert_pilot_gate_open(
                        tenant_id=node.tenant_id,
                        node_id=node.node_id,
                        now=_clock_now(clock),
                    ),
                    limiter=_AUTHORITY_THREAD_LIMITER,
                )
            except PilotGateDenied as exc:
                raise _ApiFailure(
                    409,
                    exc.reason_code,
                    "Hosted execution is temporarily unavailable",
                ) from exc
        if not callable(getattr(intent_resolver, "preflight", None)):
            raise _ApiFailure(503, "authority_unavailable", "Core authority is unavailable")
        try:
            await anyio.to_thread.run_sync(
                intent_resolver.preflight,
                envelope,
                node,
                limiter=_AUTHORITY_THREAD_LIMITER,
            )
        except CoreAuthorityRejected as exc:
            raise _ApiFailure(409, "preflight_conflict", "Core authority rejected the preflight scope") from exc
        except CoreAuthorityUnavailable as exc:
            raise _ApiFailure(503, "authority_unavailable", "Core authority is unavailable") from exc
        except Exception as exc:
            raise _ApiFailure(503, "authority_unavailable", "Core authority is unavailable") from exc
        response = HostedPreflightResponse(
            provider_request_id=envelope.request_id,
            request_id=envelope.request_id,
            request_hash=envelope.request_hash,
            idempotency_key=envelope.idempotency_key,
            state="dry_run_accepted",
            chain_id=envelope.chain_id,
            asset_contract=envelope.asset_contract,
            amount_atomic=envelope.amount_atomic,
            pay_to=envelope.pay_to,
            transaction_hash=None,
            submitted_at=None,
            confirmed_at=None,
            server_key_id=response_signer.key_id,
        )
        try:
            signed_response = response_signer.sign(response)
            record = repository.bind_preflight(
                PreflightRecord(
                    tenant_id=node.tenant_id,
                    node_id=node.node_id,
                    request_id=envelope.request_id,
                    idempotency_key=envelope.idempotency_key,
                    request_nonce=envelope.request_nonce,
                    capability_hash=envelope.payment_capability_hash,
                    reservation_id=envelope.reservation_id,
                    request_hash=envelope.request_hash,
                    signed_response_jws=signed_response,
                    created_at=_clock_now(clock),
                )
            )
        except RepositoryConflict as exc:
            raise _conflict_failure(exc) from exc
        except RepositoryUnavailable as exc:
            raise _ApiFailure(503, "dependency_unavailable", "service unavailable") from exc
        except (HostedProtocolError, ValueError) as exc:
            raise _ApiFailure(503, "response_signing_failed", "service unavailable") from exc
        except Exception as exc:
            raise _ApiFailure(503, "response_signing_failed", "service unavailable") from exc
        return JSONResponse(
            {"response_jws": record.signed_response_jws},
            headers={"cache-control": "no-store"},
        )

    @app.post(_EXECUTION_PATH)
    async def execute_payment(request: Request) -> JSONResponse:
        if (
            execution_repository is None
            or not callable(getattr(execution_service, "execute", None))
            or not callable(getattr(intent_resolver, "resolve", None))
        ):
            raise _ApiFailure(503, "execution_unavailable", "service unavailable")
        _, node, _ = await authenticate(request, expected_path=_EXECUTION_PATH)
        payload = await _read_json(request, max_bytes=config.max_request_body_bytes)
        _require_fields(payload, {"payment_jws"})
        payment_jws = payload["payment_jws"]
        if (
            not isinstance(payment_jws, str)
            or len(payment_jws.encode("utf-8")) > _MAX_DPOP_PROOF_BYTES
        ):
            raise _ApiFailure(400, "invalid_payment", "payment envelope is invalid")
        try:
            envelope = verify_payment_envelope(
                payment_jws,
                node.device_public_jwk,
                now=_clock_now(clock),
            )
        except (HostedProtocolError, ValueError) as exc:
            raise _ApiFailure(400, "invalid_payment", "payment envelope is invalid") from exc
        if envelope.http_path != _EXECUTION_PATH or envelope.http_method != "POST":
            raise _ApiFailure(403, "scope_mismatch", "payment scope is invalid")
        configured_chain, configured_token = _configured_chain_token(config)
        if envelope.chain_id != configured_chain or envelope.asset_contract != configured_token:
            raise _ApiFailure(403, "scope_mismatch", "payment scope is invalid")
        try:
            durable_replay = await anyio.to_thread.run_sync(
                lambda: execution_repository.find_for_identity(
                    tenant_id=node.tenant_id,
                    node_id=node.node_id,
                    idempotency_key=envelope.idempotency_key,
                ),
                limiter=_AUTHORITY_THREAD_LIMITER,
            )
            execution = None
            if (
                durable_replay is not None
                and ExecutionState(durable_replay.status)
                in _DURABLE_EXECUTION_REPLAY_STATES
            ):
                _execution_scope(node, envelope, durable_replay)
                execution = durable_replay
            if execution is None:
                await anyio.to_thread.run_sync(
                    lambda: execution_repository.assert_pilot_gate_open(
                        tenant_id=node.tenant_id,
                        node_id=node.node_id,
                        now=_clock_now(clock),
                    ),
                    limiter=_AUTHORITY_THREAD_LIMITER,
                )
                resolved = await anyio.to_thread.run_sync(
                    intent_resolver.resolve,
                    envelope,
                    node,
                    limiter=_AUTHORITY_THREAD_LIMITER,
                )
                intent = ExecutionIntent.model_validate(resolved, strict=True)
                _execution_scope(node, envelope, intent)
                execution = await anyio.to_thread.run_sync(
                    execution_service.execute,
                    intent,
                    limiter=_AUTHORITY_THREAD_LIMITER,
                )
                if any(
                    getattr(execution, field_name) != getattr(intent, field_name)
                    for field_name in ExecutionIntent.model_fields
                ):
                    raise ExecutionConflict("execution result does not match Core intent")
        except _ApiFailure:
            raise
        except CoreAuthorityUnavailable as exc:
            raise _ApiFailure(
                503,
                "authority_unavailable",
                "Core authority is unavailable",
            ) from exc
        except CoreAuthorityRejected as exc:
            raise _ApiFailure(
                409,
                "execution_conflict",
                "execution could not be accepted",
            ) from exc
        except PilotGateDenied as exc:
            raise _ApiFailure(
                409,
                exc.reason_code,
                "Hosted execution is temporarily unavailable",
            ) from exc
        except (ExecutionConflict, RelayerExecutionError, ValueError) as exc:
            raise _ApiFailure(
                409,
                "execution_conflict",
                "execution could not be accepted",
            ) from exc
        except Exception as exc:
            raise _ApiFailure(503, "execution_unavailable", "service unavailable") from exc
        try:
            response = _execution_projection(
                execution,
                server_key_id=response_signer.key_id,
            )
            signed = response_signer.sign_execution(response)
        except Exception as exc:
            raise _ApiFailure(503, "response_signing_failed", "service unavailable") from exc
        return JSONResponse(
            {"response_jws": signed},
            headers={"cache-control": "no-store"},
        )

    @app.get("/v1/executions/{execution_id}")
    async def execution_status(request: Request, execution_id: str) -> JSONResponse:
        if execution_repository is None:
            raise _ApiFailure(503, "execution_unavailable", "service unavailable")
        path = f"{_EXECUTION_PATH}/{execution_id}"
        _, node, _ = await authenticate(request, expected_path=path)
        try:
            execution = execution_repository.get_execution(execution_id)
        except Exception as exc:
            raise _ApiFailure(503, "execution_unavailable", "service unavailable") from exc
        if execution is None:
            raise _ApiFailure(404, "execution_not_found", "execution not found")
        if (
            execution.tenant_id != node.tenant_id
            or execution.node_id != node.node_id
            or execution.wallet_binding_id != node.wallet_binding_id
        ):
            raise _ApiFailure(404, "execution_not_found", "execution not found")
        configured_chain, configured_token = _configured_chain_token(config)
        if execution.chain != configured_chain or execution.token != configured_token:
            raise _ApiFailure(404, "execution_not_found", "execution not found")
        try:
            response = _execution_projection(
                execution,
                server_key_id=response_signer.key_id,
            )
            signed = response_signer.sign_execution(response)
        except Exception as exc:
            raise _ApiFailure(503, "response_signing_failed", "service unavailable") from exc
        return JSONResponse(
            {"response_jws": signed},
            headers={"cache-control": "no-store"},
        )

    @app.get(f"{_EXECUTION_LOOKUP_PATH}/{{idempotency_key}}")
    async def execution_lookup(request: Request, idempotency_key: str) -> JSONResponse:
        if execution_repository is None:
            raise _ApiFailure(503, "execution_unavailable", "service unavailable")
        idempotency_key = _path_identifier(
            idempotency_key, field_name="idempotency_key"
        )
        path = f"{_EXECUTION_LOOKUP_PATH}/{idempotency_key}"
        _, node, _ = await authenticate(request, expected_path=path)
        try:
            execution = execution_repository.find_for_identity(
                tenant_id=node.tenant_id,
                node_id=node.node_id,
                idempotency_key=idempotency_key,
            )
        except Exception as exc:
            raise _ApiFailure(503, "execution_unavailable", "service unavailable") from exc
        if execution is None:
            raise _ApiFailure(404, "execution_not_found", "execution not found")
        if execution.wallet_binding_id != node.wallet_binding_id:
            raise _ApiFailure(404, "execution_not_found", "execution not found")
        configured_chain, configured_token = _configured_chain_token(config)
        if execution.chain != configured_chain or execution.token != configured_token:
            raise _ApiFailure(404, "execution_not_found", "execution not found")
        try:
            response = _execution_projection(
                execution,
                server_key_id=response_signer.key_id,
            )
            signed = response_signer.sign_execution(response)
        except Exception as exc:
            raise _ApiFailure(503, "response_signing_failed", "service unavailable") from exc
        return JSONResponse(
            {"response_jws": signed},
            headers={"cache-control": "no-store"},
        )

    return app


def _clock_now(clock: Callable[[], int]) -> int:
    value = clock()
    if type(value) is not int or value <= 0:
        raise _ApiFailure(503, "clock_unavailable", "service unavailable")
    return value
