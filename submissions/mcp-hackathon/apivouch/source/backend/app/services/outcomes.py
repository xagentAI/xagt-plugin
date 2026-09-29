from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import math
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx
from cryptography.exceptions import InvalidSignature
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.core import signing
from app.core.config import GIT_COMMIT, MAX_LAB_RECEIPTS, MAX_OUTCOME_RECEIPTS
from app.models.db import OutcomeLabReceiptRow, OutcomeReceiptRow, engine
from app.services.http_client import SafeResponse, safe_request
from app.services.schemas import validate_instance


@dataclass(frozen=True)
class LabTiming:
    """Private timing context for server-owned deterministic fixtures.

    Only the Chaos Lab may supply this; production execution always uses
    the default ``None`` (real UTC clock and real monotonic latency).
    The HTTP caller can never control these values.
    """

    created_at: str
    latency_ms: int


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def digest_value(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(value).encode()).hexdigest()


def redact_url(url: str) -> str:
    """Keep provider identity while never retaining query-string values."""
    parts = urlsplit(url)
    query = urlencode([(key, "[redacted]") for key, _value in parse_qsl(parts.query, keep_blank_values=True)])
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, ""))


def provider_origin(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme.lower()}://{parts.netloc.lower()}"


def extract_path(payload: Any, path: str | None) -> Any:
    if not path:
        return payload
    current = payload
    for token in path.split("."):
        if isinstance(current, dict) and token in current:
            current = current[token]
        elif isinstance(current, list) and token.isdigit() and int(token) < len(current):
            current = current[int(token)]
        else:
            raise ValueError(f"Result path '{path}' was not present in the provider response")
    return current


def scalar_preview(value: Any) -> str | int | float | bool | None:
    if value is None or isinstance(value, (int, float, bool)):
        return value
    if isinstance(value, str):
        return value[:120]
    return None


def values_agree(left: Any, right: Any, tolerance_percent: float) -> bool:
    if isinstance(left, (int, float)) and not isinstance(left, bool) and isinstance(right, (int, float)) and not isinstance(right, bool):
        if not math.isfinite(float(left)) or not math.isfinite(float(right)):
            return False
        scale = max(abs(float(left)), abs(float(right)), 1e-12)
        return abs(float(left) - float(right)) / scale * 100 <= tolerance_percent
    return canonical_json(left) == canonical_json(right)


RequestFunction = Callable[[str, str], Awaitable[SafeResponse]]


async def probe_provider(
    provider: dict[str, Any],
    max_latency_ms: int,
    *,
    request_fn: RequestFunction | None = None,
    latency_ms_override: int | None = None,
) -> dict[str, Any]:
    started = time.perf_counter()
    base = {
        "name": provider["name"],
        "url": redact_url(provider["url"]),
        "request_url_digest": "sha256:" + hashlib.sha256(provider["url"].encode()).hexdigest(),
        "result_path": provider.get("result_path"),
        "expected_schema_digest": digest_value(provider["expected_schema"]) if provider.get("expected_schema") else None,
        "price_usd": provider.get("price_usd", 0),
        "status": "REJECTED",
        "contract_validated": False,
    }
    try:
        response = await (request_fn or safe_request)("GET", provider["url"])
        if latency_ms_override is not None:
            latency_ms = latency_ms_override
        else:
            latency_ms = max(1, int((time.perf_counter() - started) * 1000))
        base.update({"latency_ms": latency_ms, "upstream_status": response.status_code, "resolved_origin": provider_origin(response.url)})
        if not 200 <= response.status_code < 300:
            base["reason"] = f"HTTP {response.status_code}"
            return base
        if latency_ms > max_latency_ms:
            base["reason"] = f"Latency exceeded {max_latency_ms} ms"
            return base
        try:
            payload = response.json()
        except (json.JSONDecodeError, UnicodeDecodeError):
            base["reason"] = "Response was not valid JSON"
            return base
        base["response_digest"] = digest_value(payload)
        value = extract_path(payload, provider.get("result_path"))
        base["value_preview"] = scalar_preview(value)
        schema = provider.get("expected_schema")
        errors = validate_instance(value, schema) if schema else []
        if errors:
            base["reason"] = "Schema mismatch: " + "; ".join(errors[:2])
            base["value_digest"] = digest_value(value)
            return base
        base.update(
            {
                "status": "ELIGIBLE",
                "reason": None,
                "contract_validated": bool(schema),
                "value": value,
                "value_digest": digest_value(value),
            }
        )
        return base
    except (HTTPException, httpx.HTTPError, OSError, ValueError) as exc:
        if latency_ms_override is not None:
            latency_ms = latency_ms_override
        else:
            latency_ms = max(1, int((time.perf_counter() - started) * 1000))
        base.update({"latency_ms": latency_ms, "reason": str(exc)[:300]})
        return base


def _largest_agreement_group(attempts: list[dict[str, Any]], tolerance_percent: float) -> list[dict[str, Any]]:
    eligible = [attempt for attempt in attempts if attempt["status"] == "ELIGIBLE"]
    groups: list[list[dict[str, Any]]] = []
    for candidate in eligible:
        group = [other for other in eligible if values_agree(candidate["value"], other["value"], tolerance_percent)]
        if not groups or len(group) > len(groups[0]):
            groups = [group]
        elif len(group) == len(groups[0]):
            groups.append(group)
    if not groups:
        return []
    groups.sort(key=lambda group: (sum(item["price_usd"] for item in group), sum(item["latency_ms"] for item in group)))
    return groups[0]


def receipt_fingerprint(receipt_without_integrity: dict[str, Any]) -> str:
    canonical_body = dict(receipt_without_integrity)
    canonical_body.pop("integrity", None)
    canonical_body.pop("receipt_id", None)
    return "sha256:" + hashlib.sha256(canonical_json(canonical_body).encode()).hexdigest()


def verify_receipt(receipt: dict[str, Any]) -> bool:
    candidate = dict(receipt)
    integrity = candidate.pop("integrity", None) or {}
    expected = receipt_fingerprint(candidate)
    return integrity.get("fingerprint") == expected and candidate.get("receipt_id") == expected.split(":", 1)[1][:24]


def receipt_authenticity(receipt: dict[str, Any]) -> dict:
    if receipt.get("format") == "apivouch-outcome-receipt-v1" and "authenticity" not in receipt:
        return {"state": "unsigned", "valid": False}
    config = signing.SIGNING_CONFIG
    auth = receipt.get("authenticity")
    if not config.enabled or config.error:
        return {"state": "unavailable", "valid": False}
    try:
        if receipt.get("format") != "apivouch-outcome-receipt-v2" or auth != {
            "state": "signed", "algorithm": "Ed25519", "key_id": config.key_id,
        } or receipt["integrity"].get("algorithm") != "SHA-256" or not verify_receipt(receipt):
            return {"state": "invalid", "valid": False}
        signature = base64.b64decode(receipt["integrity"]["signature"], validate=True)
        config._key.public_key().verify(signature, (receipt["format"] + "\n" + receipt_fingerprint(receipt)[7:]).encode("utf-8"))
    except (ValueError, TypeError, KeyError, InvalidSignature):
        return {"state": "invalid", "valid": False}
    return {"state": "signed", "valid": True}


def store_receipt(receipt: dict[str, Any]) -> None:
    """Store production evidence; counts and evicts production rows only."""
    db = Session(engine)
    existing = db.get(OutcomeReceiptRow, receipt["receipt_id"])
    if not existing:
        overflow = db.query(OutcomeReceiptRow).count() - MAX_OUTCOME_RECEIPTS + 1
        if overflow > 0:
            oldest = db.query(OutcomeReceiptRow).order_by(OutcomeReceiptRow.created_at).limit(overflow).all()
            for row in oldest:
                db.delete(row)
    db.merge(
        OutcomeReceiptRow(
            id=receipt["receipt_id"],
            created_at=receipt["created_at"],
            receipt_json=canonical_json(receipt),
        )
    )
    db.commit()
    db.close()


def load_receipt(receipt_id: str) -> dict[str, Any] | None:
    """Load production evidence only."""
    db = Session(engine)
    row = db.get(OutcomeReceiptRow, receipt_id)
    value = json.loads(row.receipt_json) if row else None
    db.close()
    return value


class LabWriteConflict(Exception):
    """A same-ID lab row already holds different canonical JSON.

    Raised instead of overwriting conflicting evidence; carries no SQL,
    paths, driver messages, or receipt contents.
    """


class LabStorageUnavailable(Exception):
    """A lab write failed safely; carries no internals for the caller."""


_LAB_WRITE_MAX_ATTEMPTS = 3
_LAB_WRITE_RETRY_DELAY_S = 0.005
_POSTGRES_LAB_RETENTION_LOCK = text(
    "LOCK TABLE outcome_lab_receipts IN SHARE ROW EXCLUSIVE MODE"
)


def _is_transient_lab_lock_error(exc: BaseException) -> bool:
    """True only for documented transient lock/busy failures.

    SQLite reports concurrent-writer contention as SQLITE_BUSY (5) or
    SQLITE_LOCKED (6), surfaced as OperationalError. Every other database
    error must never be retried.
    """
    if not isinstance(exc, OperationalError):
        return False
    orig = getattr(exc, "orig", None)
    code = getattr(orig, "sqlite_errorcode", None)
    if code in (5, 6):
        return True
    message = str(orig or exc).lower()
    return "database is locked" in message or "database table is locked" in message


def _serialize_postgres_lab_retention(db: Session) -> None:
    """Acquire the PostgreSQL table lock used by the retention transaction."""
    if db.get_bind().dialect.name == "postgresql":
        db.execute(_POSTGRES_LAB_RETENTION_LOCK)


def _store_lab_receipt_attempt(receipt: dict[str, Any], payload: str) -> None:
    """One idempotent lab write inside context-managed transactions.

    Sessions close and failed writes roll back on every path. A uniqueness
    race resolves atomically on the primary key: after a lost insert the
    winner's row is re-read in a fresh transaction and kept only when its
    stored canonical JSON is exactly equal; conflicting evidence fails
    closed instead of being overwritten.
    """
    raced = False
    try:
        with Session(engine) as db, db.begin():
            # PostgreSQL permits concurrent writers to count the same rows,
            # so serialize this table's retention decision before reading.
            # SQLite is serialized below by flushing the insert first; that
            # acquires its database write lock before count-and-delete.
            _serialize_postgres_lab_retention(db)
            current = db.get(OutcomeLabReceiptRow, receipt["receipt_id"])
            if current is not None:
                if current.receipt_json != payload:
                    raise LabWriteConflict
                return
            db.add(
                OutcomeLabReceiptRow(
                    id=receipt["receipt_id"],
                    created_at=receipt["created_at"],
                    receipt_json=payload,
                )
            )
            # On SQLite this is the serialization boundary. It must precede
            # the retention count so concurrent distinct inserts cannot all
            # make a stale keep/evict decision. PostgreSQL is already locked.
            db.flush()
            overflow = db.query(OutcomeLabReceiptRow).count() - MAX_LAB_RECEIPTS
            if overflow > 0:
                oldest = (
                    db.query(OutcomeLabReceiptRow)
                    .filter(OutcomeLabReceiptRow.id != receipt["receipt_id"])
                    .order_by(OutcomeLabReceiptRow.created_at, OutcomeLabReceiptRow.id)
                    .limit(overflow)
                    .all()
                )
                for row in oldest:
                    db.delete(row)
    except IntegrityError:
        raced = True
    if raced:
        with Session(engine) as db:
            current = db.get(OutcomeLabReceiptRow, receipt["receipt_id"])
            if current is not None and current.receipt_json == payload:
                return
        raise LabWriteConflict


def store_lab_receipt(receipt: dict[str, Any]) -> None:
    """Store a Chaos Lab fixture receipt in the isolated lab table.

    Lab writes never count against, retain, or evict production receipts.
    Lab retention is bounded independently by MAX_LAB_RECEIPTS. Simultaneous
    identical runs are idempotent; only documented transient SQLite
    lock/busy errors are retried, at most _LAB_WRITE_MAX_ATTEMPTS attempts
    in total. All failures leave production rows unchanged and raise safe,
    content-free errors.
    """
    payload = canonical_json(receipt)
    for attempt in range(_LAB_WRITE_MAX_ATTEMPTS):
        try:
            _store_lab_receipt_attempt(receipt, payload)
            return
        except LabWriteConflict:
            raise
        except OperationalError as exc:
            if _is_transient_lab_lock_error(exc) and attempt + 1 < _LAB_WRITE_MAX_ATTEMPTS:
                time.sleep(_LAB_WRITE_RETRY_DELAY_S * (attempt + 1))
                continue
            raise LabStorageUnavailable from None
        except LabStorageUnavailable:
            raise
        except Exception:  # noqa: BLE001 - any unexpected failure maps to one safe error
            raise LabStorageUnavailable from None
    raise LabStorageUnavailable


def load_lab_receipt(receipt_id: str) -> dict[str, Any] | None:
    """Load Chaos Lab fixture evidence only."""
    with Session(engine) as db:
        row = db.get(OutcomeLabReceiptRow, receipt_id)
        return json.loads(row.receipt_json) if row else None


def load_receipt_any(receipt_id: str) -> dict[str, Any] | None:
    """Load production evidence first, then lab fixtures.

    Production receipts take precedence; a lab write can never overwrite
    or evict a production row, so collisions fail closed toward production.
    """
    value = load_receipt(receipt_id)
    if value is not None:
        return value
    return load_lab_receipt(receipt_id)


async def execute_verified_outcome(
    payload: dict[str, Any],
    *,
    require_independent_origins: bool = True,
    request_fn: RequestFunction | None = None,
    lab_timing: LabTiming | None = None,
) -> dict[str, Any]:
    signer = signing.SIGNING_CONFIG
    signer.check_issuance()
    constraints = payload["constraints"]
    names = [str(provider["name"]).casefold() for provider in payload["providers"]]
    if len(names) != len(set(names)):
        raise ValueError("Provider names must be unique")
    configured_origins = [provider_origin(provider["url"]) for provider in payload["providers"]]
    if require_independent_origins and len(configured_origins) != len(set(configured_origins)):
        raise ValueError("Every provider must use a distinct network origin")
    affordable = [provider for provider in payload["providers"] if provider.get("price_usd", 0) <= constraints["max_price_usd"]]
    over_budget = [provider for provider in payload["providers"] if provider not in affordable]
    fixed_latency = lab_timing.latency_ms if lab_timing is not None else None
    attempts = await asyncio.gather(
        *(
            probe_provider(
                provider,
                constraints["max_latency_ms"],
                request_fn=request_fn,
                latency_ms_override=fixed_latency,
            )
            for provider in affordable
        )
    )
    attempts.extend(
        {
            "name": provider["name"],
            "url": redact_url(provider["url"]),
            "request_url_digest": "sha256:" + hashlib.sha256(provider["url"].encode()).hexdigest(),
            "result_path": provider.get("result_path"),
            "expected_schema_digest": digest_value(provider["expected_schema"]) if provider.get("expected_schema") else None,
            "price_usd": provider.get("price_usd", 0),
            "status": "REJECTED",
            "contract_validated": False,
            "latency_ms": 0,
            "reason": f"Price exceeds ${constraints['max_price_usd']:.6f} budget",
        }
        for provider in over_budget
    )
    if require_independent_origins:
        resolved_origins = [attempt.get("resolved_origin") for attempt in attempts if attempt["status"] == "ELIGIBLE"]
        duplicates = {origin for origin in resolved_origins if origin and resolved_origins.count(origin) > 1}
        for attempt in attempts:
            if attempt.get("resolved_origin") in duplicates:
                attempt["status"] = "REJECTED"
                attempt["reason"] = "Provider independence failed after redirect resolution"
    agreement_group = _largest_agreement_group(attempts, constraints["numeric_tolerance_percent"])
    agreement_names = {item["name"] for item in agreement_group}
    verified = len(agreement_group) >= constraints["minimum_agreement"]
    for attempt in attempts:
        attempt["agrees_with_consensus"] = attempt["name"] in agreement_names if verified else False
        if attempt["status"] == "ELIGIBLE" and not attempt["agrees_with_consensus"]:
            attempt["status"] = "REJECTED"
            attempt["reason"] = "Result did not meet the consensus requirement" if verified else "Insufficient independent agreement"

    selected = None
    if verified:
        for attempt in agreement_group:
            latency_headroom = max(0, 1 - attempt["latency_ms"] / constraints["max_latency_ms"])
            price_denominator = max(constraints["max_price_usd"], 1e-12)
            price_headroom = max(0, 1 - attempt["price_usd"] / price_denominator)
            attempt["trust_score"] = round(70 + (10 if attempt["contract_validated"] else 0) + 10 * latency_headroom + 10 * price_headroom, 1)
        selected = min(agreement_group, key=lambda item: (-item["trust_score"], item["price_usd"], item["latency_ms"], item["name"]))
        selected["status"] = "SELECTED"

    if lab_timing is not None:
        created_at = lab_timing.created_at
    else:
        created_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    public_attempts = [{key: value for key, value in attempt.items() if key != "value"} for attempt in attempts]
    receipt: dict[str, Any] = {
        "format": "apivouch-outcome-receipt-v1",
        "created_at": created_at,
        "goal": payload["goal"],
        "verdict": "VERIFIED" if selected else "UNVERIFIED",
        "result": selected.get("value") if selected else None,
        "selected_provider": selected["name"] if selected else None,
        "selected_price_usd": selected["price_usd"] if selected else 0,
        "settlement": {"mode": "quote-only", "charged": False, "note": "This release quotes provider price but does not move payment."},
        "constraints": constraints,
        "agreement": {"providers": len(agreement_group), "required": constraints["minimum_agreement"]},
        "provider_independence": {"required": require_independent_origins, "distinct_configured_origins": len(set(configured_origins))},
        "attempts": public_attempts,
        "deployment_commit": GIT_COMMIT,
    }
    if signer.enabled:
        receipt["format"] = "apivouch-outcome-receipt-v2"
        receipt["authenticity"] = {"state": "signed", "algorithm": "Ed25519", "key_id": signer.key_id}
    fingerprint = receipt_fingerprint(receipt)
    receipt["receipt_id"] = fingerprint.split(":", 1)[1][:24]
    receipt["integrity"] = {"algorithm": "SHA-256", "fingerprint": fingerprint, "verifiable": True}
    if signer.enabled:
        receipt["integrity"]["signature"] = signer.sign((receipt["format"] + "\n" + fingerprint[7:]).encode("utf-8"))
    return receipt
