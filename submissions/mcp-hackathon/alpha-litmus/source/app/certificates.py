"""Content-addressed certificates. Checksums are not signatures or authenticity."""
import hashlib
import json
import math
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import ValidationError

from app.contracts import Report, Verification

MAX_CERTIFICATE_BYTES = 4_000_000


def canonical_json(value: Any) -> str:
    """JSON with sorted keys, finite bounded numbers and numeric equivalence.

    1, 1.0 and negative zero have a single spelling; booleans remain booleans.
    No rounding is performed and only the JSON value domain is accepted.
    """
    def encode(item: Any, depth: int) -> str:
        if depth > 32:
            raise ValueError("canonical JSON nesting exceeds 32")
        if item is None:
            return "null"
        if isinstance(item, bool):
            return "true" if item else "false"
        if isinstance(item, (int, float)):
            if not math.isfinite(item) or abs(item) > 1e100:
                raise ValueError("nonfinite or out-of-domain number")
            number = Decimal(str(item))
            if number == 0:
                return "0"
            text = format(number, "f")
            return text.rstrip("0").rstrip(".") if "." in text else text
        if isinstance(item, str):
            return json.dumps(item, ensure_ascii=True)
        if isinstance(item, list):
            return "[" + ",".join(encode(v, depth + 1) for v in item) + "]"
        if isinstance(item, dict) and all(isinstance(k, str) for k in item):
            return "{" + ",".join(encode(k, depth + 1) + ":" + encode(item[k], depth + 1) for k in sorted(item)) + "}"
        raise ValueError("unsupported canonical JSON value")
    return encode(value, 0)


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("ascii")).hexdigest()


def content_hash(report: Report | dict[str, Any]) -> str:
    content = report.model_dump(mode="json") if isinstance(report, Report) else dict(report)
    content.pop("created_at", None)
    content.pop("report_id", None)
    content.pop("canonical_report_hash", None)
    return canonical_hash(content)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def verify_report(value: Any) -> Verification:
    """Validate schemas, checksum, decision policy and deterministic replay.

    Recalculation detects rehashed inconsistent metrics, not forged input data.
    Timestamp and commit claims cannot be authenticated offline.
    """
    from app.lab import (
        LIMITATIONS,
        NumericDomainError,
        _certificate_type,
        _decision,
        _evidence_identity,
        _presentation,
        _reconcile,
        _reference,
    )

    report_id = None
    try:
        if isinstance(value, (str, bytes)):
            if len(value) > MAX_CERTIFICATE_BYTES:
                raise ValueError("certificate exceeds size limit")
            value = json.loads(value, object_pairs_hook=_unique_object,
                               parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite JSON constant")))
        if isinstance(value, Report):
            value = value.model_dump(mode="python")
        if not isinstance(value, dict):
            raise TypeError("certificate must be a JSON object")
        if len(canonical_json(value)) > MAX_CERTIFICATE_BYTES:
            raise ValueError("certificate exceeds size limit")
        report = Report.model_validate(value)
        report_id = report.report_id
        datetime.fromisoformat(report.created_at)
        errors = []
        if content_hash(report) != report.report_id or report.canonical_report_hash != report.report_id:
            errors.append("CONTENT_HASH_MISMATCH")
        if report.mode != report.request.mode or report.symbol != report.request.symbol:
            errors.append("REQUEST_REFERENCE_MISMATCH")
            return Verification(valid=False, report_id=report_id, errors=errors)
        if report.mode == "reference":
            if report.reconciliation is not None:
                errors.append("REFERENCE_HAS_NEXUS_RECONCILIATION")
            try:
                expected = _reference(report.request)
            except NumericDomainError:
                expected = None
            if expected != report.analysis:
                errors.append("REFERENCE_REPLAY_MISMATCH")
        else:
            expected = None
            summary = report.reconciliation
            if report.analysis is not None or summary is None:
                errors.append("NEXUS_REFERENCE_MISMATCH")
            elif summary != _reconcile(report.request, summary.evidence):
                errors.append("RECONCILIATION_INCONSISTENT")
        verdict, eligible, reasons, failures = _decision(report.request, expected, report.reconciliation)
        if (report.verdict, report.eligible, report.reason_codes, report.observed_failures) != (verdict, eligible, reasons, failures):
            errors.append("DECISION_POLICY_MISMATCH")
        adjustment = "unknown" if report.request.attempted_variants is None else "not_estimated"
        if report.selection_adjustment != adjustment or report.limitations != LIMITATIONS:
            errors.append("DISCLOSURE_MISMATCH")
        boundaries, matrix = _presentation(expected, report.reconciliation, failures)
        classification, dataset_hash = _evidence_identity(report.request, report.reconciliation)
        if (report.minimal_failure_boundary != boundaries or report.test_matrix != matrix or
                report.unavailable_tests != [row.name for row in matrix if row.status == "unavailable"]):
            errors.append("TEST_MATRIX_OR_BOUNDARY_MISMATCH")
        if (report.certificate_type != _certificate_type(verdict) or report.dataset_sha256 != dataset_hash or
                report.evidence_classification != classification):
            errors.append("CERTIFICATE_METADATA_MISMATCH")
        return Verification(valid=not errors, report_id=report_id, errors=errors)
    except (ValidationError, ValueError, TypeError, OverflowError, RecursionError, UnicodeError):
        return Verification(valid=False, report_id=report_id, errors=["INVALID_CERTIFICATE"])
