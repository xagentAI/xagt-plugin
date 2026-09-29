"""Persistent, loopback-only CSV merchant for the review runtime.

The merchant is deliberately small and owns no payment authority.  It accepts
one fixed service shape, verifies the signed Core receipt before touching the
input or result store, and persists only the idempotent result mailbox.  The
receipt middleware is imported from the Marketplace package; Core is never
imported here.
"""

from __future__ import annotations

import csv
from contextlib import closing
from datetime import date
from decimal import Decimal, InvalidOperation
import hashlib
import hmac
import io
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import re
import sqlite3
import threading
import time
from typing import Any, Callable

from clink_middleware.receipt import verify_clink_receipt


_CSV_COLUMNS = (
    "transaction_id",
    "date",
    "description",
    "amount",
    "currency",
    "category",
)
_CENT = Decimal("0.01")
_ZERO = Decimal("0.00")
_MAX_ROWS = 1000
_MAX_CSV_BYTES = 128 * 1024
_MAX_HTTP_BODY_BYTES = 256 * 1024
_MAX_RECEIPT_BYTES = 16 * 1024
_MAX_IDEMPOTENCY_KEY_BYTES = 256
_RESULT_RETENTION_SECONDS = 7 * 24 * 60 * 60
_MONEY_PATTERN = re.compile(r"^[+-]?\d+\.\d{2}$")
_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_CURRENCY_PATTERN = re.compile(r"^[A-Za-z]{3}$")
_DUPLICATE_HANDLING = (
    "identical duplicate rows count toward input_row_count but are ignored "
    "once for reconciliation totals; conflicting transaction_id rows are rejected"
)


def _format_money(value: Decimal) -> str:
    """Render a finite amount with exactly two decimal places."""

    if not value.is_finite():
        raise ValueError("amount must be finite")
    if value == 0:
        value = _ZERO
    try:
        return format(value.quantize(_CENT), ".2f")
    except InvalidOperation as exc:
        raise ValueError("amount precision is invalid") from exc


def _exact_amount(value: object, expected: str) -> bool:
    """Compare Core's serialized amount by value without accepting booleans."""

    if isinstance(value, bool) or value is None:
        return False
    try:
        amount = Decimal(str(value))
        target = Decimal(expected)
    except (InvalidOperation, TypeError, ValueError):
        return False
    return amount.is_finite() and amount == target


def _same_evm_address(value: object, expected: str) -> bool:
    """EVM addresses are semantically case-insensitive but never aliases."""

    return isinstance(value, str) and value.lower() == expected.lower()


def _canonical_input_hash(value: object) -> str:
    """Match Marketplace ``PurchaseService.digest`` for the frozen request.

    The current signed Core receipt does not contain a service-input hash.  The
    review runtime therefore supplies the authoritative persisted preview hash
    through ``expected_input_hash`` and this function computes the same
    canonical hash for the HTTP body ``{"csv_text": ...}``.
    """

    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return "0x" + hashlib.sha256(raw.encode()).hexdigest()


def _parse_csv_amount(raw_value: str, row_number: int) -> Decimal:
    raw = raw_value.strip()
    if not _MONEY_PATTERN.fullmatch(raw):
        raise ValueError(f"amount is invalid on row {row_number}")
    try:
        amount = Decimal(raw)
    except InvalidOperation as exc:
        raise ValueError(f"amount is invalid on row {row_number}") from exc
    if not amount.is_finite():
        raise ValueError(f"amount is invalid on row {row_number}")
    if abs(amount) > Decimal("1000000000000"):
        raise ValueError(f"amount is out of bounds on row {row_number}")
    try:
        amount = amount.quantize(_CENT)
    except InvalidOperation as exc:
        raise ValueError(f"amount is invalid on row {row_number}") from exc
    if amount == 0:
        return _ZERO
    return amount


def _normalize_row(row: dict[str, str], row_number: int) -> dict[str, str]:
    transaction_id = row.get("transaction_id", "").strip()
    if not transaction_id:
        raise ValueError(f"transaction_id is required on row {row_number}")
    description = row.get("description", "").strip()
    if not description:
        raise ValueError(f"description is required on row {row_number}")
    category = row.get("category", "").strip()
    if not category:
        raise ValueError(f"category is required on row {row_number}")

    raw_date = row.get("date", "").strip()
    if not _DATE_PATTERN.fullmatch(raw_date):
        raise ValueError(f"date is invalid on row {row_number}")
    try:
        normalized_date = date.fromisoformat(raw_date).isoformat()
    except ValueError as exc:
        raise ValueError(f"date is invalid on row {row_number}") from exc

    raw_currency = row.get("currency", "").strip()
    if not _CURRENCY_PATTERN.fullmatch(raw_currency):
        raise ValueError(f"currency is invalid on row {row_number}")
    currency = raw_currency.upper()
    amount = _parse_csv_amount(row.get("amount", ""), row_number)

    return {
        "transaction_id": transaction_id,
        "date": normalized_date,
        "description": description,
        "amount": _format_money(amount),
        "currency": currency,
        "category": category,
    }


def reconcile_csv(csv_text: str) -> dict[str, Any]:
    """Normalize and reconcile a single-currency expense CSV.

    Amounts are signed.  Positive amounts contribute to ``income_totals``;
    negative amounts contribute their absolute value to ``expense_totals``;
    ``net_totals`` and ``by_category`` retain the signed direction.  Exact
    duplicate rows are counted as input rows and reported by ID, then counted
    once in all totals.  A duplicate ID whose normalized row differs is an
    error because silently choosing one row would make reconciliation unsafe.
    """

    if not isinstance(csv_text, str):
        raise ValueError("csv_text must be a string")
    try:
        encoded = csv_text.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValueError("CSV must be valid UTF-8") from exc
    if len(encoded) > _MAX_CSV_BYTES:
        raise ValueError("CSV exceeds 128 KiB")

    try:
        reader = csv.reader(io.StringIO(csv_text, newline=""), strict=True)
        rows = iter(reader)
        try:
            header = next(rows)
        except StopIteration as exc:
            raise ValueError("CSV header is required") from exc
        if header:
            header[0] = header[0].lstrip("\ufeff")
        header = [item.strip() for item in header]
        if len(header) != len(_CSV_COLUMNS) or set(header) != set(_CSV_COLUMNS):
            raise ValueError(
                "CSV header must contain "
                "transaction_id,date,description,amount,currency,category"
            )
        if len(set(header)) != len(header):
            raise ValueError("CSV header contains duplicate columns")
        indexes = {name: header.index(name) for name in _CSV_COLUMNS}

        normalized_rows: dict[str, dict[str, str]] = {}
        duplicate_ids: list[str] = []
        input_row_count = 0
        currencies: set[str] = set()
        for row_number, values in enumerate(rows, start=2):
            if not values or all(not value.strip() for value in values):
                continue
            if len(values) != len(_CSV_COLUMNS):
                raise ValueError(f"CSV row {row_number} has the wrong number of columns")
            input_row_count += 1
            if input_row_count > _MAX_ROWS:
                raise ValueError("CSV cannot contain more than 1000 rows")
            raw_row = {
                name: values[indexes[name]]
                for name in _CSV_COLUMNS
            }
            normalized = _normalize_row(raw_row, row_number)
            transaction_id = normalized["transaction_id"]
            existing = normalized_rows.get(transaction_id)
            if existing is not None:
                if existing != normalized:
                    raise ValueError(
                        f"conflicting duplicate transaction_id {transaction_id!r}"
                    )
                if transaction_id not in duplicate_ids:
                    duplicate_ids.append(transaction_id)
                continue
            normalized_rows[transaction_id] = normalized
            currencies.add(normalized["currency"])
            if len(currencies) > 1:
                raise ValueError("mixed currencies are not supported")
    except csv.Error as exc:
        raise ValueError("CSV is malformed") from exc

    income_totals: dict[str, Decimal] = {}
    expense_totals: dict[str, Decimal] = {}
    net_totals: dict[str, Decimal] = {}
    by_category: dict[str, dict[str, Decimal]] = {}

    for row in normalized_rows.values():
        currency = row["currency"]
        amount = Decimal(row["amount"])
        net_totals[currency] = net_totals.get(currency, _ZERO) + amount
        if amount > 0:
            income_totals[currency] = income_totals.get(currency, _ZERO) + amount
        elif amount < 0:
            expense_totals[currency] = expense_totals.get(currency, _ZERO) - amount
        category_totals = by_category.setdefault(row["category"], {})
        category_totals[currency] = category_totals.get(currency, _ZERO) + amount

    def render_totals(values: dict[str, Decimal]) -> dict[str, str]:
        return {
            currency: _format_money(amount)
            for currency, amount in values.items()
        }

    return {
        "input_row_count": input_row_count,
        "unique_transaction_count": len(normalized_rows),
        "duplicate_ids": duplicate_ids,
        "duplicate_handling": _DUPLICATE_HANDLING,
        "income_totals": render_totals(income_totals),
        "expense_totals": render_totals(expense_totals),
        "net_totals": render_totals(net_totals),
        "by_category": {
            category: render_totals(totals)
            for category, totals in by_category.items()
        },
    }


class _MerchantRequestError(Exception):
    def __init__(self, status: int, error: str, message: str | None = None):
        super().__init__(message or error)
        self.status = status
        self.error = error
        self.message = message or error


class _MerchantHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, handler, merchant: "ReviewMerchant"):
        self.merchant = merchant
        super().__init__(address, handler)


class _MerchantHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        if self.path != "/v1/reconcile":
            self._send(404, {"error": "not_found"})
            return
        self.server.merchant._handle_post(self)  # type: ignore[attr-defined]

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        self._send(404, {"error": "not_found"})

    def do_PUT(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        self._send(405, {"error": "method_not_allowed"})

    def do_DELETE(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        self._send(405, {"error": "method_not_allowed"})

    def _send(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        try:
            self.wfile.write(body)
        except OSError:
            pass

    def log_message(self, _format: str, *_args: object) -> None:
        # Request headers include signed receipts and idempotency keys.
        return


class ReviewMerchant:
    """Run the review merchant on loopback with restart-safe result replay."""

    merchant_id = "commerce_analytics"

    def __init__(
        self,
        state_dir: Path,
        *,
        receipt_secret: str,
        network: str,
        token: str,
        pay_to: str,
        port: int,
        resource: str | None = None,
        expected_input_hash: Callable[[str], str | None] | None = None,
    ) -> None:
        if not isinstance(state_dir, Path):
            state_dir = Path(state_dir)
        if not isinstance(receipt_secret, str) or not receipt_secret:
            raise ValueError("receipt_secret is required")
        for name, value in (
            ("network", network),
            ("token", token),
            ("pay_to", pay_to),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} is required")
        if isinstance(port, bool) or not isinstance(port, int) or not 0 <= port <= 65535:
            raise ValueError("port must be between 0 and 65535")
        if expected_input_hash is not None and not callable(expected_input_hash):
            raise ValueError("expected_input_hash must be callable")

        self.state_dir = state_dir.expanduser().resolve()
        self.receipt_secret = receipt_secret
        self.network = network
        self.token = token
        self.pay_to = pay_to
        self.port = port
        self.resource = resource.strip() if isinstance(resource, str) and resource.strip() else None
        self.expected_input_hash = expected_input_hash
        self._server: _MerchantHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._started = threading.Event()
        self._db_path = self.state_dir / "review-merchant.sqlite3"

    @property
    def endpoint(self) -> str:
        server = self._server
        if server is not None:
            actual_port = int(server.server_address[1])
        elif self.port:
            actual_port = self.port
        else:
            raise RuntimeError("ReviewMerchant endpoint is unavailable before entering context")
        return f"http://127.0.0.1:{actual_port}/v1/reconcile"

    @property
    def receipt_resource(self) -> str:
        """Return the signed logical resource bound to this merchant."""

        return self.resource or self.endpoint

    def __enter__(self) -> "ReviewMerchant":
        if self._server is not None:
            return self
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self._initialize_database()
        try:
            server = _MerchantHTTPServer(("127.0.0.1", self.port), _MerchantHandler, self)
        except Exception:
            raise
        self._server = server
        self._started.clear()
        self._thread = threading.Thread(
            target=self._serve,
            name="review-merchant-http",
            daemon=True,
        )
        self._thread.start()
        if not self._started.wait(timeout=5):
            self.__exit__(None, None, None)
            raise RuntimeError("review merchant HTTP server did not start")
        return self

    def __exit__(self, _exc_type, _exc_value, _traceback) -> bool:
        server, self._server = self._server, None
        thread, self._thread = self._thread, None
        if server is not None:
            server.shutdown()
            server.server_close()
        if thread is not None:
            thread.join(timeout=5)
        self._started.clear()
        return False

    @property
    def delivery_count(self) -> int:
        """Return unique successfully stored purchase results.

        Replays and process restarts read the same SQLite rows, so this count
        does not increase when an already delivered purchase is requested
        again.  Expired result payloads retain their idempotency tombstone and
        remain part of the unique delivery count.
        """

        if not self._db_path.exists():
            return 0
        with closing(sqlite3.connect(self._db_path, timeout=5)) as connection:
            with connection:
                self._prune_expired(connection)
                row = connection.execute(
                    "SELECT COUNT(*) FROM merchant_results"
                ).fetchone()
        return int(row[0]) if row else 0

    def _serve(self) -> None:
        server = self._server
        if server is None:
            return
        self._started.set()
        server.serve_forever(poll_interval=0.05)

    def _initialize_database(self) -> None:
        with closing(sqlite3.connect(self._db_path, timeout=5)) as connection:
            with connection:
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS merchant_results (
                        purchase_id TEXT PRIMARY KEY,
                        input_hash TEXT NOT NULL,
                        result_json TEXT,
                        created_at INTEGER NOT NULL
                    )
                    """
                )
                self._prune_expired(connection)

    @staticmethod
    def _prune_expired(connection: sqlite3.Connection) -> None:
        """Clear expired payloads while retaining an idempotency tombstone."""

        cutoff = int(time.time()) - _RESULT_RETENTION_SECONDS
        connection.execute(
            """
            UPDATE merchant_results
            SET result_json = NULL
            WHERE result_json IS NOT NULL AND created_at < ?
            """,
            (cutoff,),
        )

    def _handle_post(self, handler: _MerchantHandler) -> None:
        try:
            purchase_id, csv_text, input_hash = self._read_request(handler)
            stored = self._stored_result(purchase_id)
            if stored is not None:
                stored_hash, stored_result = stored
                if not hmac.compare_digest(stored_hash, input_hash):
                    raise _MerchantRequestError(
                        409,
                        "idempotency_conflict",
                        "Idempotency-Key was previously used with different input",
                    )
                handler._send(200, stored_result)
                return

            result = reconcile_csv(csv_text)
            payload = {
                **result,
                "purchase_id": purchase_id,
                "input_hash": input_hash,
                "real_funds": False,
                "settlement_mode": "simulated",
            }
            stored_result = self._store_result(purchase_id, input_hash, payload)
            handler._send(200, stored_result)
        except _MerchantRequestError as exc:
            handler._send(
                exc.status,
                {"error": exc.error, "message": exc.message},
            )
        except ValueError as exc:
            handler._send(400, {"error": "invalid_request", "message": str(exc)})
        except Exception:
            # Do not echo callback, SQLite, or receipt parser details to the
            # caller.  The process remains available for a safe retry.
            handler._send(500, {"error": "merchant_unavailable"})

    def _read_request(
        self, handler: _MerchantHandler
    ) -> tuple[str, str, str]:
        purchase_id = handler.headers.get("Idempotency-Key")
        if not purchase_id:
            raise _MerchantRequestError(400, "idempotency_key_required")
        if "\r" in purchase_id or "\n" in purchase_id:
            raise _MerchantRequestError(400, "invalid_idempotency_key")
        if len(purchase_id.encode("utf-8")) > _MAX_IDEMPOTENCY_KEY_BYTES:
            raise _MerchantRequestError(400, "invalid_idempotency_key")

        receipt_token = handler.headers.get("X-CLINK-PAYMENT-RECEIPT")
        if not receipt_token:
            raise _MerchantRequestError(401, "invalid_payment_receipt")
        if len(receipt_token.encode("ascii", errors="ignore")) > _MAX_RECEIPT_BYTES:
            raise _MerchantRequestError(413, "payment_receipt_too_large")

        raw_length = handler.headers.get("Content-Length")
        try:
            body_length = int(raw_length) if raw_length is not None else -1
        except ValueError as exc:
            raise _MerchantRequestError(400, "invalid_content_length") from exc
        if body_length < 0:
            raise _MerchantRequestError(411, "content_length_required")
        if body_length > _MAX_HTTP_BODY_BYTES:
            raise _MerchantRequestError(413, "request_too_large")
        body = handler.rfile.read(body_length)
        if len(body) != body_length:
            raise _MerchantRequestError(400, "incomplete_request")
        try:
            decoded = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise _MerchantRequestError(400, "invalid_json") from exc
        if not isinstance(decoded, dict) or set(decoded) != {"csv_text"}:
            raise _MerchantRequestError(400, "request_body_must_contain_csv_text")
        csv_text = decoded.get("csv_text")
        if not isinstance(csv_text, str):
            raise _MerchantRequestError(400, "csv_text_must_be_string")

        self._verify_receipt(receipt_token, purchase_id)
        input_hash = _canonical_input_hash({"csv_text": csv_text})
        expected_input_hash = self._expected_hash(purchase_id)
        if not hmac.compare_digest(expected_input_hash, input_hash):
            raise _MerchantRequestError(
                409,
                "input_hash_mismatch",
                "request input does not match the Core preview input",
            )
        return purchase_id, csv_text, input_hash

    def _expected_hash(self, purchase_id: str) -> str:
        callback = self.expected_input_hash
        if callback is None:
            raise _MerchantRequestError(
                503,
                "input_hash_unavailable",
                "Core preview input hash is unavailable",
            )
        try:
            value = callback(purchase_id)
        except Exception as exc:
            raise _MerchantRequestError(
                503,
                "input_hash_unavailable",
                "Core preview input hash is unavailable",
            ) from exc
        if not isinstance(value, str) or not value:
            raise _MerchantRequestError(
                503,
                "input_hash_unavailable",
                "Core preview input hash is unavailable",
            )
        return value

    def _verify_receipt(self, token: str, purchase_id: str) -> dict[str, Any]:
        try:
            receipt = verify_clink_receipt(
                token,
                secret=self.receipt_secret,
                merchant_id=self.merchant_id,
                resource=self.receipt_resource,
            )
            if not isinstance(receipt, dict):
                raise ValueError("receipt is not an object")
            scope = receipt.get("metadata", {}).get("receipt_scope")
            if not isinstance(scope, dict):
                raise ValueError("signed receipt scope is missing")
            expected_scope = {
                "merchant_id": self.merchant_id,
                "resource": self.receipt_resource,
                "purchase_id": purchase_id,
                "chain": self.network,
                "token_address": self.token,
                "pay_to": self.pay_to,
                "amount_usdc": "0.30",
                "amount_atomic": "300000",
                "status": "settled",
            }
            for name, expected in expected_scope.items():
                if name in {"token_address", "pay_to"}:
                    matches = _same_evm_address(scope.get(name), expected)
                elif name == "amount_usdc":
                    matches = _exact_amount(scope.get(name), expected)
                else:
                    matches = scope.get(name) == expected
                if not matches:
                    raise ValueError(f"receipt {name} scope mismatch")
            if receipt.get("resource") != self.receipt_resource:
                raise ValueError("receipt resource mismatch")
            if receipt.get("status") != "settled":
                raise ValueError("receipt is not settled")
            if receipt.get("chain") != self.network:
                raise ValueError("receipt network mismatch")
            if not _same_evm_address(receipt.get("token_address"), self.token):
                raise ValueError("receipt token address mismatch")
            if not _same_evm_address(receipt.get("destination"), self.pay_to):
                raise ValueError("receipt payee mismatch")
            if not _exact_amount(receipt.get("amount_usdc"), "0.30"):
                raise ValueError("receipt price mismatch")
            if receipt.get("amount_atomic") not in {None, "300000"}:
                raise ValueError("receipt atomic amount mismatch")
            return receipt
        except _MerchantRequestError:
            raise
        except Exception as exc:
            raise _MerchantRequestError(
                401,
                "invalid_payment_receipt",
                "Core payment receipt could not be verified",
            ) from exc

    def _stored_result(self, purchase_id: str) -> tuple[str, dict[str, Any]] | None:
        with closing(sqlite3.connect(self._db_path, timeout=5)) as connection:
            with connection:
                self._prune_expired(connection)
                row = connection.execute(
                    "SELECT input_hash, result_json FROM merchant_results WHERE purchase_id = ?",
                    (purchase_id,),
                ).fetchone()
        if row is None:
            return None
        if row[1] is None:
            raise _MerchantRequestError(
                410,
                "stored_result_expired",
                "stored merchant result has expired; a new purchase is required",
            )
        try:
            result = json.loads(row[1])
        except (TypeError, json.JSONDecodeError) as exc:
            raise _MerchantRequestError(
                503,
                "stored_result_unavailable",
                "stored merchant result is invalid",
            ) from exc
        if not isinstance(result, dict):
            raise _MerchantRequestError(
                503,
                "stored_result_unavailable",
                "stored merchant result is invalid",
            )
        return str(row[0]), result

    def _store_result(
        self,
        purchase_id: str,
        input_hash: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        try:
            with closing(sqlite3.connect(self._db_path, timeout=5)) as connection:
                with connection:
                    connection.execute("BEGIN IMMEDIATE")
                    existing = connection.execute(
                        "SELECT input_hash, result_json FROM merchant_results WHERE purchase_id = ?",
                        (purchase_id,),
                    ).fetchone()
                    if existing is not None:
                        if not hmac.compare_digest(str(existing[0]), input_hash):
                            raise _MerchantRequestError(
                                409,
                                "idempotency_conflict",
                                "Idempotency-Key was previously used with different input",
                            )
                        if existing[1] is None:
                            raise _MerchantRequestError(
                                410,
                                "stored_result_expired",
                                "stored merchant result has expired; a new purchase is required",
                            )
                        result = json.loads(existing[1])
                        connection.commit()
                        return result
                    connection.execute(
                        "INSERT INTO merchant_results "
                        "(purchase_id, input_hash, result_json, created_at) "
                        "VALUES (?, ?, ?, ?)",
                        (purchase_id, input_hash, encoded, int(time.time())),
                    )
                    connection.commit()
        except _MerchantRequestError:
            raise
        except sqlite3.Error as exc:
            raise _MerchantRequestError(
                503,
                "result_store_unavailable",
                "merchant result could not be stored",
            ) from exc
        return payload
