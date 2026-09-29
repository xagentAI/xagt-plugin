"""Verify the authenticated HTTP review API using only stdlib HTTP calls.

The bearer token is read from an environment variable and is never accepted as
a command-line value. Output is deliberately limited to public, sanitized
purchase and budget evidence.
"""

from __future__ import annotations

import argparse
from decimal import Decimal, InvalidOperation
import json
import os
from pathlib import Path
import re
import sys
from typing import Any
from urllib.parse import urljoin

# Make both ``python -m scripts.verify_review_api`` and the documented direct
# ``python scripts/verify_review_api.py`` invocation resolve the local helper.
if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.check_review_container import (
    DEFAULT_PROJECT_SLUG,
    RequestFn,
    VerificationError,
    check_public_surface,
    normalize_base_url,
    request_json,
)


SYNTHETIC_CSV = (
    "transaction_id,date,description,amount,currency,category\n"
    "t1,2026-09-01,Hosting,-12.50,USD,software\n"
    "t2,2026-09-02,Invoice,40.00,USD,revenue\n"
    "t1,2026-09-01,Hosting,-12.50,USD,software\n"
)
IDEMPOTENCY_KEY = "review-verifier-synthetic-csv"


def _call(
    requester: RequestFn,
    method: str,
    url: str,
    *,
    token: str | None = None,
    payload: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, Any]]:
    return requester(
        method,
        url,
        token=token,
        payload=payload,
        headers=headers,
    )


def _status(
    requester: RequestFn,
    method: str,
    url: str,
    expected: int,
    message: str,
    *,
    token: str | None = None,
    payload: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    status, value = _call(
        requester,
        method,
        url,
        token=token,
        payload=payload,
        headers=headers,
    )
    if status != expected:
        raise VerificationError(message)
    return value


def _require_mode(value: dict[str, Any], *, context: str) -> None:
    if (
        value.get("real_funds") is not False
        or value.get("settlement_mode") != "simulated"
        or value.get("service_transport") != "http"
    ):
        raise VerificationError(f"{context} does not disclose the review sandbox limits")


def _decimal(value: Any, *, field: str) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise VerificationError(f"budget field {field} is invalid")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise VerificationError(f"budget field {field} is invalid") from exc
    if not result.is_finite():
        raise VerificationError(f"budget field {field} is invalid")
    return result


def _budget(value: dict[str, Any]) -> dict[str, Any]:
    required = (
        "used_amount_usdc",
        "settlement_submissions",
        "merchant_deliveries",
    )
    if any(field not in value for field in required):
        raise VerificationError("budget response is missing settlement counters")
    used = _decimal(value["used_amount_usdc"], field="used_amount_usdc")
    if isinstance(value["settlement_submissions"], bool) or not isinstance(
        value["settlement_submissions"], int
    ):
        raise VerificationError("budget field settlement_submissions is invalid")
    if isinstance(value["merchant_deliveries"], bool) or not isinstance(
        value["merchant_deliveries"], int
    ):
        raise VerificationError("budget field merchant_deliveries is invalid")
    return {
        "budget_usdc": str(value.get("budget_usdc", "")),
        "used_amount_usdc": format(used.quantize(Decimal("0.01")), ".2f"),
        "remaining_amount_usdc": str(value.get("remaining_amount_usdc", "")),
        "settlement_submissions": value["settlement_submissions"],
        "merchant_deliveries": value["merchant_deliveries"],
        "real_funds": value.get("real_funds"),
        "settlement_mode": value.get("settlement_mode"),
        "service_transport": value.get("service_transport"),
    }


def _purchase(value: dict[str, Any], *, preview_id: str, purchase_id: str) -> dict[str, Any]:
    if value.get("purchase_id") != purchase_id or value.get("preview_id") != preview_id:
        raise VerificationError("purchase identity did not remain stable")
    if value.get("state") != "delivered":
        raise VerificationError("purchase did not reach delivered state")
    _require_mode(value, context="purchase response")
    result = value.get("service_result")
    if not isinstance(result, dict):
        raise VerificationError("purchase result is missing")
    if result.get("net_totals") != {"USD": "27.50"}:
        raise VerificationError("purchase report net total is not USD 27.50")
    if result.get("unique_transaction_count") != 2 or result.get("duplicate_ids") != ["t1"]:
        raise VerificationError("purchase report does not match the synthetic CSV")
    return {
        "purchase_id": purchase_id,
        "preview_id": preview_id,
        "state": value["state"],
        "real_funds": value["real_funds"],
        "settlement_mode": value["settlement_mode"],
        "service_transport": value["service_transport"],
        "service_result": {
            "unique_transaction_count": result["unique_transaction_count"],
            "duplicate_ids": list(result["duplicate_ids"]),
            "net_totals": dict(result["net_totals"]),
        },
    }


def _write_evidence(path: Path, evidence: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(evidence, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    os.chmod(path, 0o600)


def _validate_token(token: str) -> None:
    if not re.fullmatch(r"[\x21-\x7e]{32,256}", token):
        raise VerificationError("review token environment value is invalid")


def _validate_ids(purchase_id: str | None, preview_id: str | None) -> None:
    if purchase_id is not None and not re.fullmatch(r"purchase_[A-Za-z0-9]+", purchase_id):
        raise VerificationError("purchase id is invalid")
    if preview_id is not None and not re.fullmatch(r"preview_[A-Za-z0-9]+", preview_id):
        raise VerificationError("preview id is invalid")


def _verify_replay(
    requester: RequestFn,
    origin: str,
    token: str,
    *,
    preview_id: str,
    purchase_id: str,
    expected_purchase: dict[str, Any],
    before: dict[str, Any],
) -> dict[str, Any]:
    replay_response = _status(
        requester,
        "POST",
        urljoin(origin + "/", "v1/purchases"),
        200,
        "purchase replay failed",
        token=token,
        payload={"preview_id": preview_id},
    )
    replay = _purchase(replay_response, preview_id=preview_id, purchase_id=purchase_id)
    after = _budget(
        _status(
            requester,
            "GET",
            urljoin(origin + "/", "v1/budget"),
            200,
            "budget read after replay failed",
            token=token,
        )
    )
    charge_unchanged = all(
        after[field] == before[field]
        for field in ("used_amount_usdc", "settlement_submissions", "merchant_deliveries")
    )
    if not charge_unchanged:
        raise VerificationError("purchase replay changed settlement counters")
    same_result = replay == expected_purchase
    if not same_result:
        raise VerificationError("purchase replay returned a different result")
    return {
        "purchase": replay,
        "budget_after_replay": after,
        "same_result": same_result,
        "charge_unchanged": charge_unchanged,
    }


def verify_api(
    base_url: str,
    expected_commit: str,
    token: str,
    *,
    project_slug: str = DEFAULT_PROJECT_SLUG,
    purchase_id: str | None = None,
    preview_id: str | None = None,
    requester: RequestFn = request_json,
) -> dict[str, Any]:
    """Run the first-run purchase check or a restart-only replay check."""

    if (purchase_id is None) != (preview_id is None):
        raise VerificationError("purchase-id and preview-id must be supplied together")
    _validate_token(token)
    _validate_ids(purchase_id, preview_id)
    origin = normalize_base_url(base_url)
    public = check_public_surface(
        origin,
        expected_commit,
        project_slug=project_slug,
        requester=requester,
    )
    unauthorized_status, _ = _call(
        requester,
        "GET",
        urljoin(origin + "/", "v1/budget"),
    )
    if unauthorized_status != 401:
        raise VerificationError("unauthenticated budget request was not rejected")

    if purchase_id is None or preview_id is None:
        before = _budget(
            _status(
                requester,
                "GET",
                urljoin(origin + "/", "v1/budget"),
                200,
                "initial budget read failed",
                token=token,
            )
        )
        preview_response = _status(
            requester,
            "POST",
            urljoin(origin + "/", "v1/previews"),
            200,
            "preview creation failed",
            token=token,
            payload={"offering_id": "csv-reconciliation-v1", "csv_text": SYNTHETIC_CSV},
            headers={"Idempotency-Key": IDEMPOTENCY_KEY},
        )
        preview_id = preview_response.get("preview_id")
        if not isinstance(preview_id, str) or not preview_id:
            raise VerificationError("preview response did not return an id")
        _require_mode(preview_response, context="preview response")

        purchase_response = _status(
            requester,
            "POST",
            urljoin(origin + "/", "v1/purchases"),
            200,
            "purchase failed",
            token=token,
            payload={"preview_id": preview_id},
        )
        purchase_id = purchase_response.get("purchase_id")
        if not isinstance(purchase_id, str) or not purchase_id:
            raise VerificationError("purchase response did not return an id")
        purchase = _purchase(
            purchase_response,
            preview_id=preview_id,
            purchase_id=purchase_id,
        )
        after = _budget(
            _status(
                requester,
                "GET",
                urljoin(origin + "/", "v1/budget"),
                200,
                "budget read after purchase failed",
                token=token,
            )
        )
        if _decimal(after["used_amount_usdc"], field="used_amount_usdc") - _decimal(
            before["used_amount_usdc"], field="used_amount_usdc"
        ) != Decimal("0.30"):
            raise VerificationError("purchase did not consume exactly 0.30 sandbox USDC")
        if after["settlement_submissions"] != before["settlement_submissions"] + 1:
            raise VerificationError("purchase did not create exactly one settlement submission")
        replay = _verify_replay(
            requester,
            origin,
            token,
            preview_id=preview_id,
            purchase_id=purchase_id,
            expected_purchase=purchase,
            before=after,
        )
        return {
            "base_url": origin,
            "public": public,
            "unauthorized_status": unauthorized_status,
            "preview_id": preview_id,
            "purchase_id": purchase_id,
            "purchase": purchase,
            "budget_before": before,
            "budget_after": after,
            "replay": replay,
        }

    purchase_response = _status(
        requester,
        "GET",
        urljoin(origin + "/", f"v1/purchases/{purchase_id}"),
        200,
        "persisted purchase read failed",
        token=token,
    )
    purchase = _purchase(
        purchase_response,
        preview_id=preview_id,
        purchase_id=purchase_id,
    )
    before = _budget(
        _status(
            requester,
            "GET",
            urljoin(origin + "/", "v1/budget"),
            200,
            "restart budget read failed",
            token=token,
        )
    )
    replay = _verify_replay(
        requester,
        origin,
        token,
        preview_id=preview_id,
        purchase_id=purchase_id,
        expected_purchase=purchase,
        before=before,
    )
    if replay["purchase"]["service_result"] != purchase["service_result"]:
        raise VerificationError("persisted purchase result changed after restart")
    return {
        "base_url": origin,
        "public": public,
        "unauthorized_status": unauthorized_status,
        "preview_id": preview_id,
        "purchase_id": purchase_id,
        "purchase": purchase,
        "budget_before": before,
        "restart_check": {
            "same_result": True,
            "charge_unchanged": replay["charge_unchanged"],
            "budget_after_replay": replay["budget_after_replay"],
        },
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--project-slug", default=DEFAULT_PROJECT_SLUG)
    parser.add_argument("--token-env", default="AGENTONOMY_API_TOKEN")
    parser.add_argument("--purchase-id")
    parser.add_argument("--preview-id")
    parser.add_argument("--evidence-file", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    token = os.environ.get(args.token_env, "")
    try:
        evidence = verify_api(
            args.base_url,
            args.expected_commit,
            token,
            project_slug=args.project_slug,
            purchase_id=args.purchase_id,
            preview_id=args.preview_id,
        )
        if args.evidence_file is not None:
            _write_evidence(args.evidence_file, evidence)
    except VerificationError as exc:
        print(f"review API verification failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(evidence, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
