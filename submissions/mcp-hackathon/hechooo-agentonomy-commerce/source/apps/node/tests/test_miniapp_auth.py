from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import tomllib
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qsl, quote, urlencode

from clink_node.miniapp import auth as miniapp_auth
from clink_node.miniapp.auth import (
    MiniAppAuthError,
    derive_browser_token,
    hash_browser_token,
    new_browser_session_id,
    validate_telegram_init_data,
)


class TelegramInitDataTests(unittest.TestCase):
    BOT_TOKEN = b"123456789:unit-test-bot-token"
    NOW = datetime(2026, 8, 18, 9, 30, tzinfo=UTC)
    MAX_AGE_SECONDS = 300
    USER = {
        "id": 987654321,
        "username": "agentonomy_user",
        "first_name": "Allowlisted fields only",
        "is_bot": False,
    }

    def _signed_init_data(
        self,
        *,
        auth_date: datetime | None = None,
        user_json: str | None = None,
        include_auth_date: bool = True,
        include_user: bool = True,
        order: tuple[str, ...] = ("query_id", "user", "auth_date"),
    ) -> str:
        values = {
            "query_id": "AAHdF6IQAAAAAN0XohDhrOrc",
            "user": user_json
            if user_json is not None
            else json.dumps(self.USER, separators=(",", ":")),
            "auth_date": str(int((auth_date or self.NOW).timestamp())),
        }
        if not include_auth_date:
            values.pop("auth_date")
        if not include_user:
            values.pop("user")
        secret = hmac.new(
            b"WebAppData",
            self.BOT_TOKEN,
            hashlib.sha256,
        ).digest()
        data_check_string = "\n".join(
            f"{key}={value}" for key, value in sorted(values.items())
        )
        telegram_hash = hmac.new(
            secret,
            data_check_string.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        fields = [(key, values[key]) for key in order if key in values]
        fields.append(("hash", telegram_hash))
        return urlencode(fields, quote_via=quote)

    def _assert_redacted_failure(self, init_data: str) -> MiniAppAuthError:
        with self.assertRaises(MiniAppAuthError) as raised:
            validate_telegram_init_data(
                init_data,
                bot_token=self.BOT_TOKEN,
                now=self.NOW,
                max_age_seconds=self.MAX_AGE_SECONDS,
            )

        error = raised.exception
        self.assertEqual(str(error), "telegram_auth_failed")
        self.assertEqual(
            repr(error),
            "MiniAppAuthError('telegram_auth_failed')",
        )
        current: BaseException | None = error
        visited: set[int] = set()
        while current is not None and id(current) not in visited:
            visited.add(id(current))
            rendered = f"{current!s}\n{current!r}"
            self.assertNotIn(init_data, rendered)
            self.assertNotIn(self.BOT_TOKEN.decode("ascii"), rendered)
            current = current.__cause__ or current.__context__
        self.assertIsNone(error.__cause__)
        self.assertIsNone(error.__context__)
        return error

    def test_valid_init_data_returns_allowlisted_numeric_identity(self) -> None:
        init_data = self._signed_init_data()

        identity = validate_telegram_init_data(
            init_data,
            bot_token=self.BOT_TOKEN,
            now=self.NOW,
            max_age_seconds=self.MAX_AGE_SECONDS,
        )

        self.assertEqual(identity.user_id, 987654321)
        self.assertIsInstance(identity.user_id, int)
        self.assertEqual(identity.username, "agentonomy_user")
        self.assertEqual(identity.auth_date, self.NOW)
        supplied_hash = dict(parse_qsl(init_data))["hash"]
        self.assertEqual(
            identity.exchange_hash,
            hashlib.sha256(bytes.fromhex(supplied_hash)).hexdigest(),
        )
        self.assertEqual(
            set(identity.__dataclass_fields__),
            {"user_id", "username", "auth_date", "exchange_hash"},
        )

    def test_equivalent_query_encodings_share_one_exchange_hash(self) -> None:
        canonical_order = self._signed_init_data()
        reordered = self._signed_init_data(
            order=("auth_date", "query_id", "user"),
        )
        equivalent_percent_encoding = canonical_order.replace("%20", "+")
        self.assertNotEqual(canonical_order, equivalent_percent_encoding)

        first = validate_telegram_init_data(
            canonical_order,
            bot_token=self.BOT_TOKEN,
            now=self.NOW,
            max_age_seconds=self.MAX_AGE_SECONDS,
        )
        second = validate_telegram_init_data(
            reordered,
            bot_token=self.BOT_TOKEN,
            now=self.NOW,
            max_age_seconds=self.MAX_AGE_SECONDS,
        )
        third = validate_telegram_init_data(
            equivalent_percent_encoding,
            bot_token=self.BOT_TOKEN,
            now=self.NOW,
            max_age_seconds=self.MAX_AGE_SECONDS,
        )

        self.assertEqual(first.user_id, second.user_id)
        self.assertEqual(first.auth_date, second.auth_date)
        self.assertEqual(first.exchange_hash, second.exchange_hash)
        self.assertEqual(first.exchange_hash, third.exchange_hash)

    def test_different_signed_payloads_have_different_exchange_hashes(
        self,
    ) -> None:
        first_init_data = self._signed_init_data()
        changed_user = {**self.USER, "username": "another_user"}
        second_init_data = self._signed_init_data(
            user_json=json.dumps(changed_user, separators=(",", ":")),
        )

        first = validate_telegram_init_data(
            first_init_data,
            bot_token=self.BOT_TOKEN,
            now=self.NOW,
            max_age_seconds=self.MAX_AGE_SECONDS,
        )
        second = validate_telegram_init_data(
            second_init_data,
            bot_token=self.BOT_TOKEN,
            now=self.NOW,
            max_age_seconds=self.MAX_AGE_SECONDS,
        )

        self.assertNotEqual(first.exchange_hash, second.exchange_hash)

    def test_oversized_utf8_value_is_rejected_before_expensive_work(
        self,
    ) -> None:
        init_data = f"query_id={'界' * 5_500}&hash={'0' * 64}"
        self.assertLess(len(init_data), 16 * 1024)
        self.assertGreater(len(init_data.encode("utf-8")), 16 * 1024)
        real_hmac_new = hmac.new

        with (
            patch.object(
                miniapp_auth,
                "_has_malformed_percent_encoding",
                wraps=miniapp_auth._has_malformed_percent_encoding,
            ) as percent_scanner,
            patch.object(
                miniapp_auth,
                "parse_qsl",
                wraps=parse_qsl,
            ) as query_parser,
            patch.object(
                miniapp_auth.hmac,
                "new",
                wraps=real_hmac_new,
            ) as hmac_new,
        ):
            self._assert_redacted_failure(init_data)

        self.assertEqual(
            (
                percent_scanner.call_count,
                query_parser.call_count,
                hmac_new.call_count,
            ),
            (0, 0, 0),
        )

    def test_missing_username_is_returned_as_none(self) -> None:
        user = {"id": self.USER["id"], "first_name": "No username"}
        init_data = self._signed_init_data(
            user_json=json.dumps(user, separators=(",", ":")),
        )

        identity = validate_telegram_init_data(
            init_data,
            bot_token=self.BOT_TOKEN,
            now=self.NOW,
            max_age_seconds=self.MAX_AGE_SECONDS,
        )

        self.assertIsNone(identity.username)

    def test_invalid_inputs_share_one_redacted_failure(self) -> None:
        valid = self._signed_init_data()
        malformed_percent = valid.replace("%7B", "%ZZ", 1)
        self.assertNotEqual(malformed_percent, valid)
        mismatched_hash = valid[:-1] + ("0" if valid[-1] != "0" else "1")
        hash_prefix, supplied_hash = valid.rsplit("&hash=", 1)
        uppercase_hash = hash_prefix + "&hash=" + supplied_hash.upper()
        self.assertNotEqual(uppercase_hash, valid)
        cases = {
            "malformed percent encoding": malformed_percent,
            "invalid UTF-8 input": "user=\ud800",
            "duplicate key": (
                valid + "&auth_date=" + str(int(self.NOW.timestamp()))
            ),
            "invalid user JSON": self._signed_init_data(user_json="{"),
            "missing hash": valid.rsplit("&hash=", 1)[0],
            "hash mismatch": mismatched_hash,
            "uppercase hash": uppercase_hash,
            "non-hex hash": (
                hash_prefix + "&hash=" + supplied_hash[:-1] + "g"
            ),
            "short hash": hash_prefix + "&hash=" + supplied_hash[:-1],
            "long hash": hash_prefix + "&hash=" + supplied_hash + "0",
            "missing user": self._signed_init_data(include_user=False),
            "missing auth date": self._signed_init_data(
                include_auth_date=False,
            ),
            "stale auth date": self._signed_init_data(
                auth_date=self.NOW
                - timedelta(seconds=self.MAX_AGE_SECONDS + 1),
            ),
            "future auth date": self._signed_init_data(
                auth_date=self.NOW + timedelta(seconds=1),
            ),
        }

        for label, init_data in cases.items():
            with self.subTest(label=label):
                self._assert_redacted_failure(init_data)

    def test_non_numeric_user_id_is_rejected(self) -> None:
        user = {"id": "987654321", "username": "not_numeric"}
        init_data = self._signed_init_data(
            user_json=json.dumps(user, separators=(",", ":")),
        )

        self._assert_redacted_failure(init_data)


class BrowserTokenTests(unittest.TestCase):
    SECRET = b"s" * 32
    SESSION_ID = "AbCdEfGhIjKlMnOpQrStUvWxYz012345"

    def _assert_browser_failure(
        self,
        callback,
        *sensitive_values: bytes | str,
    ) -> None:
        with self.assertRaises(MiniAppAuthError) as raised:
            callback()

        error = raised.exception
        self.assertEqual(str(error), "browser_session_failed")
        self.assertEqual(
            repr(error),
            "MiniAppAuthError('browser_session_failed')",
        )
        current: BaseException | None = error
        visited: set[int] = set()
        while current is not None and id(current) not in visited:
            visited.add(id(current))
            rendered = f"{current!s}\n{current!r}"
            for sensitive_value in sensitive_values:
                candidates = {repr(sensitive_value)}
                if isinstance(sensitive_value, bytes):
                    candidates.add(sensitive_value.decode("ascii"))
                else:
                    candidates.add(sensitive_value)
                for candidate in candidates:
                    if candidate:
                        self.assertNotIn(candidate, rendered)
            current = current.__cause__ or current.__context__
        self.assertIsNone(error.__cause__)
        self.assertIsNone(error.__context__)

    def test_new_browser_session_id_is_192_bit_urlsafe_value(self) -> None:
        first = new_browser_session_id()
        second = new_browser_session_id()

        self.assertRegex(first, re.compile(r"^[A-Za-z0-9_-]{32}$"))
        self.assertRegex(second, re.compile(r"^[A-Za-z0-9_-]{32}$"))
        self.assertNotEqual(first, second)

    def test_browser_tokens_are_deterministic_and_domain_separated(self) -> None:
        session_token = derive_browser_token(
            self.SECRET,
            self.SESSION_ID,
            purpose="session",
        )
        repeated = derive_browser_token(
            self.SECRET,
            self.SESSION_ID,
            purpose="session",
        )
        csrf_token = derive_browser_token(
            self.SECRET,
            self.SESSION_ID,
            purpose="csrf",
        )
        domain = (
            b"clink-miniapp-browser-v1\x00"
            + b"session"
            + b"\x00"
            + self.SESSION_ID.encode("ascii")
        )
        expected = base64.urlsafe_b64encode(
            hmac.new(self.SECRET, domain, hashlib.sha256).digest()
        ).decode("ascii").rstrip("=")

        self.assertEqual(session_token, expected)
        self.assertEqual(repeated, session_token)
        self.assertNotEqual(csrf_token, session_token)
        self.assertRegex(session_token, re.compile(r"^[A-Za-z0-9_-]{43}$"))
        self.assertNotIn(self.SESSION_ID, session_token)
        self.assertNotIn(self.SECRET.decode("ascii"), session_token)

    def test_storage_scope_is_stable_per_canonical_subject_and_domain_separated(
        self,
    ) -> None:
        derive = getattr(miniapp_auth, "derive_storage_scope", None)
        self.assertTrue(callable(derive))
        first = derive(self.SECRET, "telegram:101")
        repeated = derive(self.SECRET, "telegram:101")
        other_subject = derive(self.SECRET, "telegram:202")
        domain = (
            b"clink-miniapp-storage-scope-v1\x00"
            + b"local-storage"
            + b"\x00"
            + b"telegram:101"
        )
        expected = base64.urlsafe_b64encode(
            hmac.new(self.SECRET, domain, hashlib.sha256).digest()
        ).decode("ascii").rstrip("=")

        self.assertEqual(first, expected)
        self.assertEqual(repeated, first)
        self.assertNotEqual(other_subject, first)
        self.assertRegex(first, re.compile(r"^[A-Za-z0-9_-]{43}$"))
        self.assertNotEqual(first, derive_browser_token(
            self.SECRET,
            self.SESSION_ID,
            purpose="session",
        ))

    def test_storage_scope_rejects_noncanonical_subjects(self) -> None:
        derive = getattr(miniapp_auth, "derive_storage_scope", None)
        self.assertTrue(callable(derive))
        for subject_id in (
            "",
            "telegram:0",
            "telegram:0101",
            "telegram:-1",
            " telegram:101",
            "telegram:101 ",
            "telegram:１２３",
            "other:101",
        ):
            with self.subTest(subject_id=subject_id):
                with self.assertRaises(MiniAppAuthError):
                    derive(self.SECRET, subject_id)

    def test_browser_token_hash_is_lowercase_sha256(self) -> None:
        token = derive_browser_token(
            self.SECRET,
            self.SESSION_ID,
            purpose="session",
        )

        token_hash = hash_browser_token(token)

        self.assertEqual(
            token_hash,
            hashlib.sha256(token.encode("ascii")).hexdigest(),
        )
        self.assertRegex(token_hash, re.compile(r"^[0-9a-f]{64}$"))
        self.assertNotEqual(token_hash, token)

    def test_browser_token_derivation_rejects_invalid_parameters(self) -> None:
        cases = {
            "empty secret": (
                lambda: derive_browser_token(
                    b"",
                    self.SESSION_ID,
                    purpose="session",
                ),
                (b"", self.SESSION_ID),
            ),
            "short secret": (
                lambda: derive_browser_token(
                    b"s" * 31,
                    self.SESSION_ID,
                    purpose="session",
                ),
                (b"s" * 31, self.SESSION_ID),
            ),
            "short session id": (
                lambda: derive_browser_token(
                    self.SECRET,
                    "a" * 31,
                    purpose="session",
                ),
                (self.SECRET, "a" * 31),
            ),
            "long session id": (
                lambda: derive_browser_token(
                    self.SECRET,
                    "a" * 33,
                    purpose="session",
                ),
                (self.SECRET, "a" * 33),
            ),
            "non-urlsafe session id": (
                lambda: derive_browser_token(
                    self.SECRET,
                    "a" * 31 + "+",
                    purpose="session",
                ),
                (self.SECRET, "a" * 31 + "+"),
            ),
            "unknown purpose": (
                lambda: derive_browser_token(
                    self.SECRET,
                    self.SESSION_ID,
                    purpose="other",  # type: ignore[arg-type]
                ),
                (self.SECRET, self.SESSION_ID, "other"),
            ),
        }

        for label, (callback, sensitive_values) in cases.items():
            with self.subTest(label=label):
                self._assert_browser_failure(callback, *sensitive_values)


class MiniAppPackagingTests(unittest.TestCase):
    def test_miniapp_package_is_in_the_explicit_package_list(self) -> None:
        pyproject_path = Path(__file__).resolve().parents[1] / "pyproject.toml"
        with pyproject_path.open("rb") as handle:
            pyproject = tomllib.load(handle)

        packages = pyproject["tool"]["setuptools"]["packages"]
        self.assertIn("clink_node.miniapp", packages)


if __name__ == "__main__":
    unittest.main()
