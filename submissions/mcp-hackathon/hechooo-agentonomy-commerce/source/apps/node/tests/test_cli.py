from __future__ import annotations

import io
import json
import os
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from apps.node.clink_node.cli import (
    MINIAPP_SECRET_NAMES,
    _NoRedirectHandler,
    _check_managed_server_risk_limiter,
    _check_miniapp,
    _check_risk_provider,
    _load_core_internal_token,
    _load_core_risk_rate_limiter_class,
    _parser,
    _process_running,
    main,
)
from apps.node.clink_node.config import (
    EventBackend,
    EventSettings,
    ModuleMode,
    ModuleSettings,
    NodeSettings,
    Profile,
)
from apps.node.clink_node.paths import NodePaths


class SlowDripResponse:
    def __init__(self, payload: bytes, *, interval_seconds: float) -> None:
        self.payload = payload
        self.interval_seconds = interval_seconds
        self.closed = threading.Event()
        self.read_sizes: list[int] = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()
        return False

    def read(self, limit=-1):
        self.read_sizes.append(limit)
        body = bytearray()
        for value in self.payload:
            if self.closed.wait(self.interval_seconds):
                return bytes(body)
            body.append(value)
        return bytes(body)

    def close(self) -> None:
        self.closed.set()


class CliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.home = Path(self.temporary.name) / ".clink"
        self.environment = {
            "CLINK_HOME": str(self.home),
            "HOME": str(Path(self.temporary.name)),
        }

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def run_cli(self, *arguments: str) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with patch.dict(os.environ, self.environment, clear=True):
            with redirect_stdout(stdout), redirect_stderr(stderr):
                code = main(list(arguments))
        return code, stdout.getvalue(), stderr.getvalue()

    def use_file_secret_store(self) -> None:
        config_path = self.home / "config.toml"
        config = config_path.read_text(encoding="utf-8")
        config_path.write_text(
            config.replace(
                'backend = "keychain"',
                'backend = "file"',
                1,
            ),
            encoding="utf-8",
        )

    def test_parser_exposes_lifecycle_commands_without_auto_start(self) -> None:
        parser = _parser()

        maintenance = parser.parse_args(["maintenance", "quiesce"])
        service = parser.parse_args(["service", "status", "--systemd"])
        upgrade = parser.parse_args(["upgrade", "--version", "1.2.3"])
        rollback = parser.parse_args(["rollback"])

        self.assertEqual(maintenance.maintenance_command, "quiesce")
        self.assertTrue(service.systemd)
        self.assertEqual(upgrade.version, "1.2.3")
        self.assertEqual(rollback.command, "rollback")

    def enable_miniapp(self) -> None:
        config_path = self.home / "config.toml"
        config = config_path.read_text(encoding="utf-8")
        config_path.write_text(
            config.replace(
                "[miniapp]\nenabled = false",
                "[miniapp]\nenabled = true",
                1,
            ),
            encoding="utf-8",
        )

    def test_init_creates_one_personal_configuration(self) -> None:
        code, output, error = self.run_cli("init", "--profile", "personal")

        self.assertEqual(code, 0, error)
        self.assertTrue((self.home / "config.toml").is_file())
        self.assertTrue((self.home / "data").is_dir())
        self.assertIn("personal", output)
        config = (self.home / "config.toml").read_text(encoding="utf-8")
        self.assertIn('profile = "personal"', config)
        self.assertIn('backend = "sqlite"', config)
        self.assertIn("[miniapp]\nenabled = false", config)

    def test_secret_set_reads_only_from_non_echoing_prompt(self) -> None:
        self.run_cli("init", "--profile", "personal")
        self.use_file_secret_store()
        values = {
            "telegram-miniapp-bot-token": "bot-token-value-1234567890",
            "hermes-api-server-key": "hermes-api-value-1234567890",
            "miniapp-cookie-key": "c" * 32,
            "hermes-session-key": "s" * 32,
        }

        for name, value in values.items():
            with self.subTest(name=name):
                with patch(
                    "apps.node.clink_node.cli.getpass.getpass",
                    return_value=value,
                ):
                    code, output, error = self.run_cli(
                        "secret",
                        "set",
                        name,
                    )

                self.assertEqual(code, 0, error)
                self.assertEqual(output, "Secret stored.\n")
                self.assertNotIn(value, output)
                self.assertNotIn(value, error)

        secret_path = self.home / "secrets" / "node-secrets.json"
        self.assertEqual(secret_path.stat().st_mode & 0o777, 0o600)
        serialized = secret_path.read_text(encoding="utf-8")
        for value in values.values():
            self.assertNotIn(value, serialized)

    def test_secret_set_rejects_value_argument_and_unknown_name(self) -> None:
        self.run_cli("init", "--profile", "personal")

        accidental_value = "must-not-be-accepted"
        stdout = io.StringIO()
        stderr = io.StringIO()
        with patch.dict(os.environ, self.environment, clear=True):
            with redirect_stdout(stdout), redirect_stderr(stderr):
                with self.assertRaises(SystemExit):
                    main(
                        [
                            "secret",
                            "set",
                            "miniapp-cookie-key",
                            accidental_value,
                        ]
                    )
        self.assertNotIn(accidental_value, stdout.getvalue())
        self.assertNotIn(accidental_value, stderr.getvalue())
        with self.assertRaises(SystemExit):
            self.run_cli("secret", "set", "other-secret")

    def test_secret_set_rejects_invalid_values_without_echoing_them(
        self,
    ) -> None:
        self.run_cli("init", "--profile", "personal")
        self.use_file_secret_store()
        cases = (
            ("telegram-miniapp-bot-token", ""),
            ("hermes-api-server-key", "line\nbreak"),
            ("hermes-api-server-key", "contains space"),
            ("hermes-api-server-key", "非ascii"),
            ("miniapp-cookie-key", "too-short"),
            ("hermes-session-key", "x" * 4097),
        )

        for name, value in cases:
            with self.subTest(name=name, length=len(value)):
                with patch(
                    "apps.node.clink_node.cli.getpass.getpass",
                    return_value=value,
                ):
                    code, output, error = self.run_cli(
                        "secret",
                        "set",
                        name,
                    )

                self.assertEqual(code, 1)
                self.assertEqual(output, "")
                if value:
                    self.assertNotIn(value, error)

    def test_doctor_checks_miniapp_secret_presence_without_values(
        self,
    ) -> None:
        self.run_cli("init", "--profile", "personal")
        self.use_file_secret_store()
        self.enable_miniapp()

        with patch(
            "apps.node.clink_node.cli._port_available",
            return_value=True,
        ):
            code, output, error = self.run_cli("doctor", "--json")

        self.assertEqual(code, 1, error)
        report = json.loads(output)
        self.assertFalse(report["checks"]["miniapp"]["ok"])
        self.assertEqual(
            report["checks"]["miniapp"]["detail"],
            "required secrets are not configured",
        )

        values = iter(
            (
                "bot-token-value-1234567890",
                "hermes-api-value-1234567890",
                "c" * 32,
                "s" * 32,
            )
        )
        with patch(
            "apps.node.clink_node.cli.getpass.getpass",
            side_effect=lambda _prompt: next(values),
        ):
            for name in (
                "telegram-miniapp-bot-token",
                "hermes-api-server-key",
                "miniapp-cookie-key",
                "hermes-session-key",
            ):
                self.assertEqual(self.run_cli("secret", "set", name)[0], 0)

        with patch(
            "apps.node.clink_node.cli._port_available",
            return_value=True,
        ):
            code, output, error = self.run_cli("doctor", "--json")

        self.assertEqual(code, 0, error)
        report = json.loads(output)
        self.assertTrue(report["checks"]["miniapp"]["ok"])
        self.assertEqual(
            report["checks"]["miniapp"]["detail"],
            "configured",
        )
        self.assertNotIn("bot-token-value", output)
        self.assertNotIn("hermes-api-value", output)

    def test_doctor_checks_all_four_miniapp_secret_names(self) -> None:
        settings = NodeSettings.defaults(
            Profile.PERSONAL,
            paths=NodePaths.from_home(self.home),
        )
        settings = replace(
            settings,
            miniapp=replace(settings.miniapp, enabled=True),
        )

        class RecordingStore:
            def __init__(self) -> None:
                self.names: list[str] = []

            def get(self, name: str) -> None:
                self.names.append(name)
                return None

        store = RecordingStore()
        with patch(
            "apps.node.clink_node.application._secret_store",
            return_value=store,
        ):
            result = _check_miniapp(settings)

        self.assertEqual(
            store.names,
            list(MINIAPP_SECRET_NAMES),
        )
        self.assertEqual(
            result,
            (False, "required secrets are not configured"),
        )

    def test_doctor_treats_malformed_miniapp_secrets_as_unconfigured(
        self,
    ) -> None:
        settings = NodeSettings.defaults(
            Profile.PERSONAL,
            paths=NodePaths.from_home(self.home),
        )
        settings = replace(
            settings,
            miniapp=replace(settings.miniapp, enabled=True),
        )
        valid = {
            "telegram-miniapp-bot-token": b"bot-token",
            "hermes-api-server-key": b"hermes-key",
            "miniapp-cookie-key": b"c" * 32,
            "hermes-session-key": b"s" * 32,
        }
        cases = (
            ("telegram-miniapp-bot-token", "not-bytes"),
            ("miniapp-cookie-key", b"short"),
            ("hermes-api-server-key", b"line\nbreak"),
            ("hermes-api-server-key", b"non-ascii-\xff"),
            ("hermes-session-key", b"x" * 4_097),
        )

        for name, malformed in cases:
            with self.subTest(name=name, value_type=type(malformed)):
                values = dict(valid)
                values[name] = malformed

                class MappingStore:
                    def get(self, requested: str) -> object:
                        return values.get(requested)

                with patch(
                    "apps.node.clink_node.application._secret_store",
                    return_value=MappingStore(),
                ):
                    result = _check_miniapp(settings)

                self.assertEqual(
                    result,
                    (False, "required secrets are not configured"),
                )

    def test_doctor_reports_machine_readable_configuration(self) -> None:
        self.run_cli("init", "--profile", "personal")

        with patch(
            "apps.node.clink_node.cli._port_available",
            return_value=True,
        ):
            code, output, error = self.run_cli("doctor", "--json")

        self.assertEqual(code, 0, error)
        report = json.loads(output)
        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["profile"], "personal")
        self.assertTrue(report["checks"]["repository_layout"]["ok"])
        self.assertTrue(report["checks"]["ports"]["ok"])
        self.assertTrue(report["checks"]["storage"]["ok"])
        self.assertTrue(report["checks"]["events"]["ok"])

    def test_doctor_shadow_without_key_performs_no_external_probe(self) -> None:
        self.run_cli("init", "--profile", "personal")

        with patch(
            "apps.node.clink_node.cli._open_local_misttrack_status"
        ) as urlopen:
            with patch(
                "apps.node.clink_node.cli._port_available",
                return_value=True,
            ):
                code, output, error = self.run_cli("doctor", "--json")

        self.assertEqual(code, 0, error)
        check = json.loads(output)["checks"]["risk_provider"]
        self.assertTrue(check["ok"])
        self.assertEqual(
            check,
            {
                "ok": True,
                "detail": "not_required",
                "provider": "misttrack",
                "mode": "shadow",
                "configured": False,
                "probe": "not_required",
            },
        )
        urlopen.assert_not_called()

    def test_doctor_rejects_invalid_shadow_configuration_without_probe(self) -> None:
        self.run_cli("init", "--profile", "personal")
        invalid_settings = (
            ("CLINK_RISK_MODE", "invalid"),
            ("CLINK_RISK_PROVIDER", "other"),
            ("MISTTRACK_BASE_URL", "http://openapi.misttrack.io"),
            ("MISTTRACK_TIMEOUT_SECONDS", "nan"),
            ("MISTTRACK_TIMEOUT_SECONDS", "31"),
            ("MISTTRACK_MAX_ATTEMPTS", "0"),
            ("MISTTRACK_MAX_ATTEMPTS", "6"),
            ("CLINK_RISK_HOLD_SCORE", "71"),
            ("CLINK_RISK_DENY_SCORE", "31"),
            ("CLINK_RISK_MAX_AGE_SECONDS", "0"),
            ("CLINK_RISK_CACHE_TTL_SECONDS", "0"),
            ("CLINK_RISK_CACHE_TTL_SECONDS", "86401"),
        )

        for name, value in invalid_settings:
            with self.subTest(name=name, value=value):
                self.environment[name] = value
                with patch(
                    "apps.node.clink_node.cli._open_local_misttrack_status"
                ) as urlopen:
                    with patch(
                        "apps.node.clink_node.cli._port_available",
                        return_value=True,
                    ):
                        code, output, error = self.run_cli("doctor", "--json")
                self.environment.pop(name)

                self.assertEqual(code, 1, error)
                check = json.loads(output)["checks"]["risk_provider"]
                self.assertEqual(check["detail"], "invalid_configuration")
                self.assertEqual(check["probe"], "invalid_configuration")
                urlopen.assert_not_called()

    def test_doctor_enforce_without_key_fails_not_configured(self) -> None:
        self.run_cli("init", "--profile", "personal")
        self.environment["CLINK_RISK_MODE"] = "enforce"

        with patch(
            "apps.node.clink_node.cli._open_local_misttrack_status"
        ) as urlopen:
            with patch(
                "apps.node.clink_node.cli._port_available",
                return_value=True,
            ):
                code, output, error = self.run_cli("doctor", "--json")

        self.assertEqual(code, 1, error)
        check = json.loads(output)["checks"]["risk_provider"]
        self.assertFalse(check["ok"])
        self.assertEqual(check["detail"], "not_configured")
        self.assertFalse(check["configured"])
        urlopen.assert_not_called()

    def test_doctor_rejects_non_exact_misttrack_base_url_without_probe(self) -> None:
        self.run_cli("init", "--profile", "personal")
        for base_url in (
            "https://openapi.misttrack.io////",
            "https://openapi.misttrack.io:invalid",
        ):
            with self.subTest(base_url=base_url):
                self.environment.update(
                    {
                        "CLINK_RISK_MODE": "enforce",
                        "MISTTRACK_API_KEY": "test-key",
                        "MISTTRACK_BASE_URL": base_url,
                    }
                )

                with patch(
                    "apps.node.clink_node.cli._open_local_misttrack_status"
                ) as urlopen:
                    with patch(
                        "apps.node.clink_node.cli._port_available",
                        return_value=True,
                    ):
                        code, output, error = self.run_cli("doctor", "--json")

                self.assertEqual(code, 1, error)
                self.assertEqual(
                    json.loads(output)["checks"]["risk_provider"]["detail"],
                    "invalid_configuration",
                )
                urlopen.assert_not_called()

    def test_doctor_redacts_misttrack_key_on_failed_probe(self) -> None:
        self.run_cli("init", "--profile", "personal")
        key = "doctor-test-key-must-not-leak"
        self.environment.update(
            {"CLINK_RISK_MODE": "enforce", "MISTTRACK_API_KEY": key}
        )
        failure = urllib.error.URLError(
            f"offline https://openapi.misttrack.io/v1/status?api_key={key}"
        )

        with patch(
            "apps.node.clink_node.cli._open_local_misttrack_status",
            side_effect=failure,
        ):
            with patch(
                "apps.node.clink_node.cli._port_available",
                return_value=True,
            ):
                code, output, error = self.run_cli("doctor", "--json")

        serialized = output + error
        self.assertEqual(code, 1)
        self.assertNotIn(key, serialized)
        self.assertNotIn("api_key=", serialized)
        self.assertNotIn("https://", serialized)
        check = json.loads(output)["checks"]["risk_provider"]
        self.assertEqual(check["detail"], "unavailable")
        self.assertEqual(check["provider"], "misttrack")
        self.assertEqual(check["mode"], "enforce")
        self.assertTrue(check["configured"])
        self.assertEqual(check["probe"], "unavailable")

    def test_doctor_rejects_malformed_misttrack_keys_without_leaking(
        self,
    ) -> None:
        self.run_cli("init", "--profile", "personal")
        malformed_keys = (
            "control-key\nsecret",
            "surrogate-key-\ud800-secret",
            "x" * 4_097,
        )

        for key in malformed_keys:
            with self.subTest(key_length=len(key)):
                values = {
                    "CLINK_RISK_MODE": "enforce",
                    "MISTTRACK_API_KEY": key,
                }
                with patch(
                    "apps.node.clink_node.cli.os.getenv",
                    side_effect=lambda name, default=None: values.get(
                        name,
                        default,
                    ),
                ), patch(
                    "apps.node.clink_node.cli._open_local_misttrack_status"
                ) as urlopen, patch(
                    "apps.node.clink_node.cli._port_available",
                    return_value=True,
                ):
                    code, output, error = self.run_cli("doctor", "--json")

                serialized = output + error
                self.assertEqual(code, 1)
                check = json.loads(output)["checks"]["risk_provider"]
                self.assertEqual(check["detail"], "invalid_configuration")
                self.assertEqual(check["probe"], "invalid_configuration")
                self.assertNotIn(key, serialized)
                self.assertNotIn("api_key=", serialized)
                urlopen.assert_not_called()

    def test_local_probe_construction_failures_are_redacted(self) -> None:
        self.run_cli("init", "--profile", "personal")
        key = "local-construction-key-must-not-leak"
        self.environment.update(
            {
                "CLINK_RISK_MODE": "enforce",
                "MISTTRACK_API_KEY": key,
            }
        )

        for target, error_type in (
            (
                "apps.node.clink_node.cli.urllib.parse.urlsplit",
                RuntimeError,
            ),
            (
                "apps.node.clink_node.cli.urllib.parse.urlencode",
                ValueError,
            ),
            (
                "apps.node.clink_node.cli.urllib.request.Request",
                ValueError,
            ),
        ):
            with self.subTest(target=target), patch(
                target,
                side_effect=error_type(
                    f"failed with api_key={key} at https://private.example"
                ),
            ), patch(
                "apps.node.clink_node.cli._open_local_misttrack_status"
            ) as urlopen, patch(
                "apps.node.clink_node.cli._port_available",
                return_value=True,
            ):
                code, output, error = self.run_cli("doctor", "--json")

            serialized = output + error
            self.assertEqual(code, 1)
            check = json.loads(output)["checks"]["risk_provider"]
            self.assertEqual(check["detail"], "invalid_configuration")
            self.assertEqual(check["probe"], "invalid_configuration")
            self.assertNotIn(key, serialized)
            self.assertNotIn("api_key=", serialized)
            self.assertNotIn("https://", serialized)
            urlopen.assert_not_called()

    def test_doctor_text_output_contains_only_redacted_risk_projection(self) -> None:
        self.run_cli("init", "--profile", "personal")
        key = "doctor-text-key-must-not-leak"
        self.environment.update(
            {"CLINK_RISK_MODE": "enforce", "MISTTRACK_API_KEY": key}
        )

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, _limit=-1):
                return b'{"success":true}'

        with patch(
            "apps.node.clink_node.cli._open_local_misttrack_status",
            return_value=Response(),
        ), patch(
            "apps.node.clink_node.cli._port_available",
            return_value=True,
        ):
            code, output, error = self.run_cli("doctor")

        serialized = output + error
        self.assertEqual(code, 0, error)
        self.assertIn("provider=misttrack", output)
        self.assertIn("mode=enforce", output)
        self.assertIn("configured=true", output)
        self.assertIn("probe=reachable", output)
        self.assertNotIn(key, serialized)
        self.assertNotIn("api_key=", serialized)
        self.assertNotIn("https://", serialized)

    def test_doctor_fails_closed_on_unknown_internal_probe_detail(self) -> None:
        self.run_cli("init", "--profile", "personal")
        marker = "https://private.example/?api_key=must-not-leak"

        with patch(
            "apps.node.clink_node.cli._check_risk_provider",
            return_value=(True, marker),
        ), patch(
            "apps.node.clink_node.cli._port_available",
            return_value=True,
        ):
            code, output, error = self.run_cli("doctor", "--json")

        serialized = output + error
        check = json.loads(output)["checks"]["risk_provider"]
        self.assertEqual(code, 1)
        self.assertFalse(check["ok"])
        self.assertEqual(check["detail"], "invalid_response")
        self.assertEqual(check["probe"], "invalid_response")
        self.assertNotIn(marker, serialized)
        self.assertNotIn("api_key=", serialized)
        self.assertNotIn("https://", serialized)

    def test_doctor_enforce_uses_official_status_endpoint(self) -> None:
        self.run_cli("init", "--profile", "personal")
        self.environment.update(
            {"CLINK_RISK_MODE": "enforce", "MISTTRACK_API_KEY": "test-key"}
        )

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, _limit=-1):
                return b'{"success":true}'

        with patch(
            "apps.node.clink_node.cli._open_local_misttrack_status",
            return_value=Response(),
        ) as urlopen:
            with patch(
                "apps.node.clink_node.cli._port_available",
                return_value=True,
            ):
                code, output, error = self.run_cli("doctor", "--json")

        self.assertEqual(code, 0, error)
        request = urlopen.call_args.args[0]
        self.assertEqual(request.method, "GET")
        self.assertEqual(
            request.full_url,
            "https://openapi.misttrack.io/v1/status?api_key=test-key",
        )
        self.assertEqual(
            json.loads(output)["checks"]["risk_provider"]["detail"],
            "reachable",
        )

    def test_local_misttrack_redirect_fails_closed_and_redacted(self) -> None:
        settings = NodeSettings.defaults(
            Profile.PERSONAL,
            paths=NodePaths.from_home(self.home),
        )
        key = "redirect-key-must-not-leak"

        class RedirectBody:
            def __init__(self) -> None:
                self.read_count = 0
                self.closed = False

            def read(self, _limit=-1):
                self.read_count += 1
                return b'{"success":true}'

            def close(self) -> None:
                self.closed = True

        body = RedirectBody()

        class Opener:
            def __init__(self) -> None:
                self.request = None
                self.timeout = None

            def open(self, request, *, timeout):
                self.request = request
                self.timeout = timeout
                raise urllib.error.HTTPError(
                    request.full_url,
                    302,
                    "Found",
                    {
                        "Location": (
                            "https://attacker.example/collect?api_key=" + key
                        )
                    },
                    body,
                )

        opener = Opener()
        with patch.dict(
            os.environ,
            {
                "CLINK_RISK_MODE": "enforce",
                "MISTTRACK_API_KEY": key,
            },
            clear=True,
        ), patch(
            "apps.node.clink_node.cli.urllib.request.build_opener",
            return_value=opener,
        ) as build_opener, patch(
            "apps.node.clink_node.cli.urllib.request.urlopen",
            side_effect=AssertionError("default redirecting opener used"),
        ):
            ok, detail = _check_risk_provider(settings)

        serialized = json.dumps({"ok": ok, "detail": detail})
        self.assertFalse(ok)
        self.assertEqual(detail, "unavailable")
        self.assertEqual(body.read_count, 0)
        self.assertTrue(body.closed)
        self.assertEqual(opener.timeout, 5.0)
        self.assertIsNotNone(opener.request)
        handler = build_opener.call_args.args[0]
        self.assertIsInstance(handler, _NoRedirectHandler)
        self.assertNotIn(key, serialized)
        self.assertNotIn("api_key=", serialized)
        self.assertNotIn("attacker.example", serialized)
        self.assertNotIn("https://", serialized)

    def test_local_misttrack_slow_drip_respects_hard_deadline(self) -> None:
        settings = NodeSettings.defaults(
            Profile.PERSONAL,
            paths=NodePaths.from_home(self.home),
        )
        key = "slow-local-key-must-not-leak"
        response = SlowDripResponse(
            b'{"success":true}',
            interval_seconds=0.02,
        )

        with patch.dict(
            os.environ,
            {
                "CLINK_RISK_MODE": "enforce",
                "MISTTRACK_API_KEY": key,
                "MISTTRACK_TIMEOUT_SECONDS": "0.05",
            },
            clear=True,
        ), patch(
            "apps.node.clink_node.cli._open_local_misttrack_status",
            return_value=response,
        ) as open_status:
            started = time.monotonic()
            result = _check_risk_provider(settings)
            elapsed = time.monotonic() - started

        serialized = repr(result)
        self.assertEqual(result, (False, "unavailable"))
        self.assertLess(elapsed, 0.2)
        self.assertTrue(response.closed.is_set())
        self.assertEqual(response.read_sizes, [4_097])
        self.assertEqual(open_status.call_args.kwargs["timeout"], 0.05)
        self.assertNotIn(key, serialized)
        self.assertNotIn("api_key=", serialized)

    def test_enforce_doctor_rejects_weaker_than_v1_thresholds(self) -> None:
        settings = NodeSettings.defaults(
            Profile.PERSONAL,
            paths=NodePaths.from_home(self.home),
        )

        with patch.dict(
            os.environ,
            {
                "CLINK_RISK_MODE": "enforce",
                "MISTTRACK_API_KEY": "test-key",
                "CLINK_RISK_HOLD_SCORE": "40",
                "CLINK_RISK_DENY_SCORE": "80",
            },
            clear=True,
        ), patch(
            "apps.node.clink_node.cli._open_local_misttrack_status",
        ) as urlopen:
            ok, detail = _check_risk_provider(settings)

        self.assertFalse(ok)
        self.assertEqual(detail, "invalid_configuration")
        urlopen.assert_not_called()

    def test_shadow_doctor_with_key_probes_provider(self) -> None:
        settings = NodeSettings.defaults(
            Profile.PERSONAL,
            paths=NodePaths.from_home(self.home),
        )

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, _limit=-1):
                return b'{"success":true}'

        with patch.dict(
            os.environ,
            {
                "CLINK_RISK_MODE": "shadow",
                "MISTTRACK_API_KEY": "test-key",
            },
            clear=True,
        ), patch(
            "apps.node.clink_node.cli._open_local_misttrack_status",
            return_value=Response(),
        ) as urlopen:
            ok, detail = _check_risk_provider(settings)

        self.assertTrue(ok)
        self.assertEqual(detail, "reachable")
        urlopen.assert_called_once()

    def test_doctor_rejects_invalid_success_response_without_echoing_body(self) -> None:
        self.run_cli("init", "--profile", "personal")
        self.environment.update(
            {"CLINK_RISK_MODE": "enforce", "MISTTRACK_API_KEY": "test-key"}
        )

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, _limit=-1):
                return b"<html>sensitive provider response</html>"

        with patch(
            "apps.node.clink_node.cli._open_local_misttrack_status",
            return_value=Response(),
        ):
            with patch(
                "apps.node.clink_node.cli._port_available",
                return_value=True,
            ):
                code, output, error = self.run_cli("doctor", "--json")

        self.assertEqual(code, 1, error)
        self.assertNotIn("sensitive provider response", output)
        self.assertEqual(
            json.loads(output)["checks"]["risk_provider"]["detail"],
            "invalid_response",
        )

    def test_server_doctor_uses_external_core_redacted_preflight(self) -> None:
        settings = NodeSettings.defaults(
            Profile.SERVER,
            paths=NodePaths.from_home(self.home),
        )
        settings = replace(
            settings,
            modules={
                **settings.modules,
                "core": ModuleSettings(
                    mode=ModuleMode.EXTERNAL,
                    endpoint="https://core.example",
                    service_urls={
                        "policy": "https://policy.core.example/base/",
                    },
                ),
            },
        )

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, _limit=-1):
                return b'{"ok":true,"detail":"reachable"}'

        with patch.dict(
            os.environ,
            {"MISTTRACK_API_KEY": "node-key-must-not-be-used"},
            clear=True,
        ), patch(
            "apps.node.clink_node.cli._load_core_internal_token",
            return_value="core-internal-test-token",
        ), patch(
            "apps.node.clink_node.cli._open_external_core_readiness",
            return_value=Response(),
        ) as urlopen:
            ok, detail = _check_risk_provider(settings)

        self.assertTrue(ok)
        self.assertEqual(detail, "reachable")
        request = urlopen.call_args.args[0]
        self.assertEqual(
            request.full_url,
            "https://policy.core.example/base/risk/readiness",
        )
        self.assertNotIn("api_key", request.full_url)
        self.assertNotIn("node-key-must-not-be-used", request.full_url)
        self.assertEqual(
            request.get_header("Authorization"),
            "Bearer core-internal-test-token",
        )

    def test_external_core_redirects_are_never_followed(self) -> None:
        request = urllib.request.Request(
            "https://policy.core.example/risk/readiness",
            headers={"Authorization": "Bearer internal-token"},
        )
        handler = _NoRedirectHandler()

        for redirect_url in (
            "https://policy.core.example/new-readiness",
            "https://attacker.example/collect",
            "http://attacker.example/collect",
        ):
            with self.subTest(redirect_url=redirect_url):
                redirected = handler.redirect_request(
                    request,
                    None,
                    302,
                    "Found",
                    {"Location": redirect_url},
                    redirect_url,
                )

                self.assertIsNone(redirected)

    def test_external_core_redirect_response_fails_closed_and_redacted(
        self,
    ) -> None:
        settings = NodeSettings.defaults(
            Profile.SERVER,
            paths=NodePaths.from_home(self.home),
        )
        settings = replace(
            settings,
            modules={
                **settings.modules,
                "core": ModuleSettings(
                    mode=ModuleMode.EXTERNAL,
                    endpoint="https://core.example",
                    service_urls={"policy": "https://policy.core.example"},
                ),
            },
        )

        class RedirectBody:
            def __init__(self) -> None:
                self.read_count = 0
                self.closed = False

            def read(self, _limit=-1):
                self.read_count += 1
                return b'{"ok":true,"detail":"reachable"}'

            def close(self) -> None:
                self.closed = True

        body = RedirectBody()

        class Opener:
            def __init__(self) -> None:
                self.request = None
                self.timeout = None

            def open(self, request, *, timeout):
                self.request = request
                self.timeout = timeout
                raise urllib.error.HTTPError(
                    request.full_url,
                    302,
                    "Found",
                    {"Location": "https://attacker.example/collect"},
                    body,
                )

        opener = Opener()
        with patch(
            "apps.node.clink_node.cli._load_core_internal_token",
            return_value="core-internal-test-token",
        ), patch(
            "apps.node.clink_node.cli.urllib.request.build_opener",
            return_value=opener,
        ) as build_opener:
            ok, detail = _check_risk_provider(settings)

        serialized = json.dumps({"ok": ok, "detail": detail})
        self.assertFalse(ok)
        self.assertEqual(detail, "unavailable")
        self.assertEqual(body.read_count, 0)
        self.assertTrue(body.closed)
        self.assertEqual(opener.timeout, 5)
        self.assertEqual(
            opener.request.get_header("Authorization"),
            "Bearer core-internal-test-token",
        )
        handler = build_opener.call_args.args[0]
        self.assertIsInstance(handler, _NoRedirectHandler)
        self.assertNotIn("core-internal-test-token", serialized)
        self.assertNotIn("attacker.example", serialized)
        self.assertNotIn("https://", serialized)

    def test_external_core_slow_drip_respects_hard_deadline(self) -> None:
        settings = NodeSettings.defaults(
            Profile.SERVER,
            paths=NodePaths.from_home(self.home),
        )
        settings = replace(
            settings,
            modules={
                **settings.modules,
                "core": ModuleSettings(
                    mode=ModuleMode.EXTERNAL,
                    endpoint="https://core.example",
                    service_urls={"policy": "https://policy.core.example"},
                ),
            },
        )
        token = "slow-core-token-must-not-leak"
        response = SlowDripResponse(
            b'{"ok":true,"detail":"reachable"}',
            interval_seconds=0.01,
        )

        with patch(
            "apps.node.clink_node.cli._EXTERNAL_CORE_READINESS_TIMEOUT_SECONDS",
            0.05,
            create=True,
        ), patch(
            "apps.node.clink_node.cli._load_core_internal_token",
            return_value=token,
        ), patch(
            "apps.node.clink_node.cli._open_external_core_readiness",
            return_value=response,
        ) as open_readiness:
            started = time.monotonic()
            result = _check_risk_provider(settings)
            elapsed = time.monotonic() - started

        serialized = repr(result)
        self.assertEqual(result, (False, "unavailable"))
        self.assertLess(elapsed, 0.2)
        self.assertTrue(response.closed.is_set())
        self.assertEqual(response.read_sizes, [4_097])
        self.assertEqual(open_readiness.call_args.kwargs["timeout"], 0.05)
        self.assertNotIn(token, serialized)
        self.assertNotIn("https://", serialized)

    def test_server_doctor_fails_closed_without_core_internal_token(self) -> None:
        settings = NodeSettings.defaults(
            Profile.SERVER,
            paths=NodePaths.from_home(self.home),
        )
        settings = replace(
            settings,
            modules={
                **settings.modules,
                "core": ModuleSettings(
                    mode=ModuleMode.EXTERNAL,
                    endpoint="https://core.example",
                    service_urls={"policy": "https://policy.core.example"},
                ),
            },
        )

        with patch(
            "apps.node.clink_node.cli._load_core_internal_token",
            return_value=None,
        ), patch(
            "apps.node.clink_node.cli._open_external_core_readiness",
        ) as urlopen:
            ok, detail = _check_risk_provider(settings)

        self.assertFalse(ok)
        self.assertEqual(detail, "invalid_configuration")
        urlopen.assert_not_called()

    def test_core_internal_token_loader_rejects_control_characters(self) -> None:
        settings = NodeSettings.defaults(
            Profile.SERVER,
            paths=NodePaths.from_home(self.home),
        )
        malformed_values = (
            b"internal\nsecret",
            b"internal\rsecret",
            b"internal\tsecret",
            b"internal\x00secret",
            b"internal\x7fsecret",
            b"x" * 4_097,
        )

        for value in malformed_values:
            with self.subTest(value_length=len(value)):
                store = type("Store", (), {"get": lambda _self, _name: value})()
                with patch(
                    "apps.node.clink_node.application._secret_store",
                    return_value=store,
                ):
                    token = _load_core_internal_token(settings)

                self.assertIsNone(token)

    def test_external_core_request_construction_failure_is_redacted(self) -> None:
        settings = NodeSettings.defaults(
            Profile.SERVER,
            paths=NodePaths.from_home(self.home),
        )
        settings = replace(
            settings,
            modules={
                **settings.modules,
                "core": ModuleSettings(
                    mode=ModuleMode.EXTERNAL,
                    endpoint="https://core.example",
                    service_urls={"policy": "https://policy.core.example"},
                ),
            },
        )
        marker = "private-core-token-must-not-leak"

        with patch(
            "apps.node.clink_node.cli._load_core_internal_token",
            return_value="valid-internal-token",
        ), patch(
            "apps.node.clink_node.cli.urllib.request.Request",
            side_effect=RuntimeError(marker),
        ), patch(
            "apps.node.clink_node.cli._open_external_core_readiness",
        ) as open_readiness:
            result = _check_risk_provider(settings)

        serialized = repr(result)
        self.assertEqual(result, (False, "invalid_configuration"))
        self.assertNotIn(marker, serialized)
        open_readiness.assert_not_called()

    def test_managed_server_doctor_requires_explicit_rate_limit(self) -> None:
        settings = NodeSettings.defaults(
            Profile.SERVER,
            paths=NodePaths.from_home(self.home),
        )

        with patch.dict(
            os.environ,
            {
                "CLINK_RISK_MODE": "shadow",
                "MISTTRACK_API_KEY": "test-key",
            },
            clear=True,
        ), patch(
            "apps.node.clink_node.cli._open_local_misttrack_status",
        ) as urlopen:
            ok, detail = _check_risk_provider(settings)

        self.assertFalse(ok)
        self.assertEqual(detail, "invalid_configuration")
        urlopen.assert_not_called()

    def test_managed_server_doctor_accepts_explicit_rate_limit(self) -> None:
        settings = NodeSettings.defaults(
            Profile.SERVER,
            paths=NodePaths.from_home(self.home),
        )

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, _limit=-1):
                return b'{"success":true}'

        with patch.dict(
            os.environ,
            {
                "CLINK_RISK_MODE": "shadow",
                "MISTTRACK_API_KEY": "test-key",
                "MISTTRACK_RATE_LIMIT_REQUESTS_PER_WINDOW": "10",
                "MISTTRACK_RATE_LIMIT_WINDOW_SECONDS": "60",
                "CLINK_REDIS_OPERATION_TIMEOUT_SECONDS": "1",
            },
            clear=True,
        ), patch(
            "apps.node.clink_node.cli._check_managed_server_risk_limiter",
            return_value=(True, "reachable"),
        ) as limiter_check, patch(
            "apps.node.clink_node.cli._open_local_misttrack_status",
            return_value=Response(),
        ) as urlopen:
            ok, detail = _check_risk_provider(settings)

        self.assertTrue(ok)
        self.assertEqual(detail, "reachable")
        limiter_check.assert_called_once_with(
            settings,
            requests_per_window=10,
            window_seconds=60,
            timeout_seconds=1.0,
        )
        urlopen.assert_called_once()

    def test_doctor_rejects_partial_or_invalid_rate_limit_config(self) -> None:
        settings = NodeSettings.defaults(
            Profile.PERSONAL,
            paths=NodePaths.from_home(self.home),
        )
        invalid_settings = (
            {"MISTTRACK_RATE_LIMIT_REQUESTS_PER_WINDOW": "10"},
            {
                "MISTTRACK_RATE_LIMIT_REQUESTS_PER_WINDOW": "0",
                "MISTTRACK_RATE_LIMIT_WINDOW_SECONDS": "60",
            },
            {
                "MISTTRACK_RATE_LIMIT_REQUESTS_PER_WINDOW": "1001",
                "MISTTRACK_RATE_LIMIT_WINDOW_SECONDS": "60",
            },
            {
                "MISTTRACK_RATE_LIMIT_REQUESTS_PER_WINDOW": "10",
                "MISTTRACK_RATE_LIMIT_WINDOW_SECONDS": "3601",
            },
            {"CLINK_REDIS_OPERATION_TIMEOUT_SECONDS": "inf"},
            {"CLINK_REDIS_OPERATION_TIMEOUT_SECONDS": "5.1"},
        )

        for overrides in invalid_settings:
            with self.subTest(overrides=overrides), patch.dict(
                os.environ,
                {"CLINK_RISK_MODE": "shadow", **overrides},
                clear=True,
            ), patch(
                "apps.node.clink_node.cli._open_local_misttrack_status",
            ) as urlopen:
                ok, detail = _check_risk_provider(settings)

            self.assertFalse(ok)
            self.assertEqual(detail, "invalid_configuration")
            urlopen.assert_not_called()

    def test_server_doctor_allows_loopback_http_core(self) -> None:
        settings = NodeSettings.defaults(
            Profile.SERVER,
            paths=NodePaths.from_home(self.home),
        )
        settings = replace(
            settings,
            modules={
                **settings.modules,
                "core": ModuleSettings(
                    mode=ModuleMode.EXTERNAL,
                    endpoint="http://127.0.0.1:8019",
                    service_urls={"policy": "http://127.0.0.1:8015"},
                ),
            },
        )

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, _limit=-1):
                return b'{"ok":true,"detail":"reachable"}'

        with patch(
            "apps.node.clink_node.cli._load_core_internal_token",
            return_value="core-internal-test-token",
        ), patch(
            "apps.node.clink_node.cli._open_external_core_readiness",
            return_value=Response(),
        ) as urlopen:
            ok, detail = _check_risk_provider(settings)

        self.assertTrue(ok)
        self.assertEqual(detail, "reachable")
        self.assertEqual(
            urlopen.call_args.args[0].full_url,
            "http://127.0.0.1:8015/risk/readiness",
        )

    def test_external_core_uses_core_preflight_regardless_of_profile(self) -> None:
        settings = NodeSettings.defaults(
            Profile.PERSONAL,
            paths=NodePaths.from_home(self.home),
        )
        settings = replace(
            settings,
            modules={
                **settings.modules,
                "core": ModuleSettings(
                    mode=ModuleMode.EXTERNAL,
                    endpoint="http://127.0.0.1:8019",
                    service_urls={"policy": "http://127.0.0.1:8015"},
                ),
            },
        )

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, _limit=-1):
                return b'{"ok":true,"detail":"not_required"}'

        with patch(
            "apps.node.clink_node.cli._load_core_internal_token",
            return_value="core-internal-test-token",
        ), patch(
            "apps.node.clink_node.cli._open_external_core_readiness",
            return_value=Response(),
        ) as urlopen:
            ok, detail = _check_risk_provider(settings)

        self.assertTrue(ok)
        self.assertEqual(detail, "not_required")
        self.assertEqual(
            urlopen.call_args.args[0].full_url,
            "http://127.0.0.1:8015/risk/readiness",
        )

    def test_external_core_preflight_rejects_unbounded_payload_fields(self) -> None:
        settings = NodeSettings.defaults(
            Profile.SERVER,
            paths=NodePaths.from_home(self.home),
        )
        settings = replace(
            settings,
            modules={
                **settings.modules,
                "core": ModuleSettings(
                    mode=ModuleMode.EXTERNAL,
                    endpoint="https://core.example",
                    service_urls={"policy": "https://policy.core.example"},
                ),
            },
        )

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, _limit=-1):
                return b'{"ok":true,"detail":"reachable","debug":"secret"}'

        with patch(
            "apps.node.clink_node.cli._load_core_internal_token",
            return_value="core-internal-test-token",
        ), patch(
            "apps.node.clink_node.cli._open_external_core_readiness",
            return_value=Response(),
        ):
            ok, detail = _check_risk_provider(settings)

        self.assertFalse(ok)
        self.assertEqual(detail, "invalid_response")

    def test_external_core_preflight_accepts_redacted_redis_failure(self) -> None:
        settings = NodeSettings.defaults(
            Profile.SERVER,
            paths=NodePaths.from_home(self.home),
        )
        settings = replace(
            settings,
            modules={
                **settings.modules,
                "core": ModuleSettings(
                    mode=ModuleMode.EXTERNAL,
                    endpoint="https://core.example",
                    service_urls={"policy": "https://policy.core.example"},
                ),
            },
        )

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, _limit=-1):
                return b'{"ok":false,"detail":"redis_unavailable"}'

        with patch(
            "apps.node.clink_node.cli._load_core_internal_token",
            return_value="core-internal-test-token",
        ), patch(
            "apps.node.clink_node.cli._open_external_core_readiness",
            return_value=Response(),
        ):
            ok, detail = _check_risk_provider(settings)

        self.assertFalse(ok)
        self.assertEqual(detail, "redis_unavailable")

    def test_external_core_preflight_rejects_contradictory_status(self) -> None:
        settings = NodeSettings.defaults(
            Profile.SERVER,
            paths=NodePaths.from_home(self.home),
        )
        settings = replace(
            settings,
            modules={
                **settings.modules,
                "core": ModuleSettings(
                    mode=ModuleMode.EXTERNAL,
                    endpoint="https://core.example",
                    service_urls={"policy": "https://policy.core.example"},
                ),
            },
        )

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, _limit=-1):
                return b'{"ok":true,"detail":"invalid_key"}'

        with patch(
            "apps.node.clink_node.cli._load_core_internal_token",
            return_value="core-internal-test-token",
        ), patch(
            "apps.node.clink_node.cli._open_external_core_readiness",
            return_value=Response(),
        ):
            ok, detail = _check_risk_provider(settings)

        self.assertFalse(ok)
        self.assertEqual(detail, "invalid_response")

    def test_external_core_preflight_rejects_false_success_detail(self) -> None:
        settings = NodeSettings.defaults(
            Profile.SERVER,
            paths=NodePaths.from_home(self.home),
        )
        settings = replace(
            settings,
            modules={
                **settings.modules,
                "core": ModuleSettings(
                    mode=ModuleMode.EXTERNAL,
                    endpoint="https://core.example",
                    service_urls={"policy": "https://policy.core.example"},
                ),
            },
        )

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, _limit=-1):
                return b'{"ok":false,"detail":"reachable"}'

        with patch(
            "apps.node.clink_node.cli._load_core_internal_token",
            return_value="core-internal-test-token",
        ), patch(
            "apps.node.clink_node.cli._open_external_core_readiness",
            return_value=Response(),
        ):
            ok, detail = _check_risk_provider(settings)

        self.assertFalse(ok)
        self.assertEqual(detail, "invalid_response")

    def test_managed_server_limiter_uses_core_limiter_and_consumes_quota(
        self,
    ) -> None:
        settings = NodeSettings.defaults(
            Profile.SERVER,
            paths=NodePaths.from_home(self.home),
        )
        settings = replace(
            settings,
            events=EventSettings(
                backend=EventBackend.REDIS,
                redis_url="rediss://redis.example/0",
            ),
        )
        events: list[str] = []
        test_case = self

        class Client:
            def close(self) -> None:
                events.append("close")

        client = Client()

        class Limiter:
            def __init__(
                self,
                actual_client,
                *,
                requests_per_window,
                window_seconds,
            ) -> None:
                test_case.assertEqual(actual_client, client)
                test_case.assertEqual(requests_per_window, 10)
                test_case.assertEqual(window_seconds, 60)

            def check_ready(self) -> None:
                events.append("check_ready")

            def acquire(self):
                events.append("acquire")
                return True, 0

        with patch(
            "apps.node.clink_node.cli._load_core_risk_rate_limiter_class",
            return_value=Limiter,
        ), patch("redis.Redis.from_url", return_value=client) as from_url:
            ok, detail = _check_managed_server_risk_limiter(
                settings,
                requests_per_window=10,
                window_seconds=60,
                timeout_seconds=1.5,
            )

        self.assertTrue(ok)
        self.assertEqual(detail, "reachable")
        self.assertEqual(events, ["check_ready", "acquire", "close"])
        from_url.assert_called_once_with(
            "rediss://redis.example/0",
            socket_connect_timeout=1.5,
            socket_timeout=1.5,
        )

    def test_node_loader_executes_the_current_core_limiter_module(self) -> None:
        limiter_class = _load_core_risk_rate_limiter_class()

        self.assertEqual(limiter_class.__name__, "RedisRiskRateLimiter")
        self.assertEqual(
            limiter_class.__module__,
            "_clink_core_risk_rate_limiter",
        )

    def test_managed_server_limiter_reports_exhausted_quota(self) -> None:
        settings = NodeSettings.defaults(
            Profile.SERVER,
            paths=NodePaths.from_home(self.home),
        )
        settings = replace(
            settings,
            events=EventSettings(
                backend=EventBackend.REDIS,
                redis_url="rediss://redis.example/0",
            ),
        )

        class Client:
            def close(self) -> None:
                pass

        class Limiter:
            def __init__(self, *_args, **_kwargs) -> None:
                pass

            def check_ready(self) -> None:
                pass

            def acquire(self):
                return False, 1_000

        with patch(
            "apps.node.clink_node.cli._load_core_risk_rate_limiter_class",
            return_value=Limiter,
        ), patch("redis.Redis.from_url", return_value=Client()):
            ok, detail = _check_managed_server_risk_limiter(
                settings,
                requests_per_window=10,
                window_seconds=60,
                timeout_seconds=1.0,
            )

        self.assertFalse(ok)
        self.assertEqual(detail, "rate_limited")

    def test_managed_server_limiter_failure_stops_before_status_probe(self) -> None:
        settings = NodeSettings.defaults(
            Profile.SERVER,
            paths=NodePaths.from_home(self.home),
        )

        with patch.dict(
            os.environ,
            {
                "CLINK_RISK_MODE": "shadow",
                "MISTTRACK_API_KEY": "test-key",
                "MISTTRACK_RATE_LIMIT_REQUESTS_PER_WINDOW": "10",
                "MISTTRACK_RATE_LIMIT_WINDOW_SECONDS": "60",
            },
            clear=True,
        ), patch(
            "apps.node.clink_node.cli._check_managed_server_risk_limiter",
            return_value=(False, "redis_unavailable"),
        ), patch(
            "apps.node.clink_node.cli._open_local_misttrack_status",
        ) as urlopen:
            ok, detail = _check_risk_provider(settings)

        self.assertFalse(ok)
        self.assertEqual(detail, "redis_unavailable")
        urlopen.assert_not_called()

    def test_managed_server_limiter_rejects_invalid_result_shape(self) -> None:
        settings = NodeSettings.defaults(
            Profile.SERVER,
            paths=NodePaths.from_home(self.home),
        )
        settings = replace(
            settings,
            events=EventSettings(
                backend=EventBackend.REDIS,
                redis_url="rediss://redis.example/0",
            ),
        )

        class Client:
            def close(self) -> None:
                pass

        class Limiter:
            def __init__(self, *_args, **_kwargs) -> None:
                pass

            def check_ready(self) -> None:
                pass

            def acquire(self):
                return True, 1

        with patch(
            "apps.node.clink_node.cli._load_core_risk_rate_limiter_class",
            return_value=Limiter,
        ), patch("redis.Redis.from_url", return_value=Client()):
            ok, detail = _check_managed_server_risk_limiter(
                settings,
                requests_per_window=10,
                window_seconds=60,
                timeout_seconds=1.0,
            )

        self.assertFalse(ok)
        self.assertEqual(detail, "redis_unavailable")

    def test_migrate_creates_the_local_database(self) -> None:
        self.run_cli("init", "--profile", "personal")

        code, output, error = self.run_cli("migrate")

        self.assertEqual(code, 0, error)
        self.assertTrue((self.home / "data" / "clink.db").is_file())
        self.assertIn("schema_version=6", output)

    def test_migrate_can_archive_legacy_state(self) -> None:
        self.run_cli("init", "--profile", "personal")
        legacy = Path(self.temporary.name) / "legacy"
        state = (
            legacy
            / "apps"
            / "marketplace"
            / "services"
            / "purchase_service"
            / "purchases.jsonl"
        )
        state.parent.mkdir(parents=True)
        state.write_text('{"purchase_id":"purchase_1"}\n')

        code, output, error = self.run_cli(
            "migrate",
            "--legacy-root",
            str(legacy),
        )

        self.assertEqual(code, 0, error)
        report = json.loads(output.splitlines()[-1])
        self.assertEqual(report["imported"], 1)
        self.assertTrue(Path(report["manifest_path"]).is_file())

    def test_status_is_stopped_without_a_pid(self) -> None:
        self.run_cli("init", "--profile", "personal")

        code, output, error = self.run_cli("status", "--json")

        self.assertEqual(code, 3, error)
        status = json.loads(output)
        self.assertFalse(status["running"])
        self.assertIsNone(status["pid"])

    def test_stop_recovers_orphaned_managed_modules_without_pid(
        self,
    ) -> None:
        self.run_cli("init", "--profile", "personal")

        with patch(
            "apps.node.clink_node.cli._stop_managed_modules"
        ) as stop_modules:
            code, output, error = self.run_cli("stop")

        self.assertEqual(code, 0, error)
        stop_modules.assert_called_once()
        self.assertIn("not running", output)

    def test_export_is_redacted(self) -> None:
        self.run_cli("init", "--profile", "personal")

        code, output, error = self.run_cli("export")

        self.assertEqual(code, 0, error)
        exported = json.loads(output)
        self.assertEqual(exported["profile"], "personal")
        self.assertNotIn("internal_api_token", output.lower())
        self.assertNotIn("private_key", output.lower())

    def test_zombie_pid_is_not_reported_as_running(self) -> None:
        completed = type(
            "Completed",
            (),
            {"returncode": 0, "stdout": "Z+\n"},
        )()
        with patch("apps.node.clink_node.cli.os.kill"):
            with patch(
                "apps.node.clink_node.cli.subprocess.run",
                return_value=completed,
            ):
                self.assertFalse(_process_running(1234))


if __name__ == "__main__":
    unittest.main()
