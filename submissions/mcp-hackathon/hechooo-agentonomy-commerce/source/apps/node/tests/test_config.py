from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from clink_node.config import (
    EventBackend,
    InteractionMode,
    ModuleMode,
    NodeSettings,
    Profile,
    SecretBackend,
    StorageBackend,
)
from clink_node.paths import NodePaths


ROOT = Path(__file__).resolve().parents[3]


class NodeSettingsTests(unittest.TestCase):
    def test_personal_profile_is_local_first(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            paths = NodePaths.from_home(Path(temporary))
            settings = NodeSettings.defaults(Profile.PERSONAL, paths=paths)

        self.assertEqual(settings.storage.backend, StorageBackend.SQLITE)
        self.assertEqual(settings.events.backend, EventBackend.MEMORY)
        self.assertEqual(settings.secrets.backend, SecretBackend.KEYCHAIN)
        self.assertEqual(settings.interaction.mode, InteractionMode.LOCAL)
        self.assertFalse(settings.multi_tenant)
        self.assertEqual(
            settings.storage.sqlite_path,
            paths.data / "clink.db",
        )
        self.assertEqual(settings.validation_errors(), [])

    def test_miniapp_defaults_are_disabled_and_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            settings = NodeSettings.defaults(
                Profile.PERSONAL,
                paths=NodePaths.from_home(Path(temporary)),
            )

        miniapp = settings.miniapp
        self.assertFalse(miniapp.enabled)
        self.assertEqual(
            miniapp.hermes_base_url,
            "http://127.0.0.1:8642",
        )
        self.assertEqual(miniapp.auth_max_age_seconds, 300)
        self.assertEqual(miniapp.session_ttl_seconds, 86_400)
        self.assertEqual(miniapp.connect_timeout_seconds, 3)
        self.assertEqual(miniapp.read_timeout_seconds, 60)
        self.assertEqual(miniapp.max_stream_seconds, 900)
        self.assertEqual(miniapp.max_active_runs_per_subject, 1)
        self.assertEqual(miniapp.ip_general_limit, 240)
        self.assertEqual(miniapp.session_exchange_limit, 10)
        self.assertEqual(miniapp.subject_general_limit, 120)
        self.assertEqual(miniapp.message_submit_limit, 12)
        self.assertEqual(miniapp.operation_link_limit, 12)
        self.assertEqual(miniapp.stop_limit, 12)
        self.assertEqual(miniapp.traffic_window_seconds, 60)
        self.assertEqual(miniapp.max_sse_per_subject, 1)
        self.assertEqual(miniapp.sse_lease_ttl_seconds, 960)
        self.assertEqual(settings.validation_errors(), [])

    def test_miniapp_toml_and_environment_overrides_are_strict(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config_path = root / "config.toml"
            config_path.write_text(
                """
[miniapp]
enabled = false
hermes_base_url = "http://localhost:8643"
auth_max_age_seconds = 120
session_ttl_seconds = 7200
connect_timeout_seconds = 2
read_timeout_seconds = 30
max_stream_seconds = 600
max_active_runs_per_subject = 1
ip_general_limit = 200
session_exchange_limit = 8
subject_general_limit = 100
message_submit_limit = 9
operation_link_limit = 7
stop_limit = 6
traffic_window_seconds = 45
max_sse_per_subject = 1
sse_lease_ttl_seconds = 900
""".strip(),
                encoding="utf-8",
            )
            settings = NodeSettings.load(
                config_path,
                env={
                    "CLINK_HOME": str(root / ".clink"),
                    "CLINK_MINIAPP_ENABLED": "true",
                    "CLINK_MINIAPP_IP_GENERAL_LIMIT": "180",
                },
            )

        self.assertTrue(settings.miniapp.enabled)
        self.assertEqual(
            settings.miniapp.hermes_base_url,
            "http://localhost:8643",
        )
        self.assertEqual(settings.miniapp.auth_max_age_seconds, 120)
        self.assertEqual(settings.miniapp.max_stream_seconds, 600)
        self.assertEqual(settings.miniapp.ip_general_limit, 180)
        self.assertEqual(settings.miniapp.message_submit_limit, 9)
        self.assertEqual(settings.validation_errors(), [])

    def test_miniapp_environment_rejects_ambiguous_boolean(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(
                ValueError,
                "CLINK_MINIAPP_ENABLED must be true or false",
            ):
                NodeSettings.load(
                    env={
                        "CLINK_HOME": temporary,
                        "CLINK_MINIAPP_ENABLED": "yes",
                    }
                )

    def test_miniapp_document_requires_a_table(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config_path = Path(temporary) / "config.toml"
            config_path.write_text(
                'miniapp = "enabled"',
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                ValueError,
                "miniapp must be a table",
            ):
                NodeSettings.load(
                    config_path,
                    env={"CLINK_HOME": temporary},
                )

    def test_miniapp_document_rejects_unknown_keys(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config_path = Path(temporary) / "config.toml"
            config_path.write_text(
                "[miniapp]\nenabeld = true",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                ValueError,
                "unknown miniapp setting: enabeld",
            ):
                NodeSettings.load(
                    config_path,
                    env={"CLINK_HOME": temporary},
                )

    def test_miniapp_rejects_non_loopback_hermes_and_fake_concurrency(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            settings = NodeSettings.load(
                env={
                    "CLINK_HOME": temporary,
                    "CLINK_MINIAPP_HERMES_BASE_URL": (
                        "https://hermes.example.test/api?key="
                        "leaked-hermes-query-token"
                    ),
                    "CLINK_MINIAPP_MAX_ACTIVE_RUNS_PER_SUBJECT": "2",
                    "CLINK_MINIAPP_MAX_SSE_PER_SUBJECT": "2",
                }
            )

        errors = settings.validation_errors()
        self.assertIn(
            "Mini App Hermes base URL must be loopback HTTP",
            errors,
        )
        self.assertIn(
            "Mini App max active runs per subject must equal 1",
            errors,
        )
        self.assertIn(
            "Mini App max SSE per subject must equal 1",
            errors,
        )
        self.assertNotIn(
            "leaked-hermes-query-token",
            repr(settings.redacted()),
        )

    def test_miniapp_direct_settings_keep_boolean_and_url_strict(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            baseline = NodeSettings.defaults(
                Profile.PERSONAL,
                paths=NodePaths.from_home(Path(temporary)),
            )

        invalid_boolean = replace(
            baseline,
            miniapp=replace(baseline.miniapp, enabled="true"),
        )
        self.assertIn(
            "Mini App enabled must be a boolean",
            invalid_boolean.validation_errors(),
        )
        for url in (
            "http://127.0.0.1:8642/?",
            "http://127.0.0.1:8642/#",
        ):
            with self.subTest(url=url):
                configured = replace(
                    baseline,
                    miniapp=replace(
                        baseline.miniapp,
                        hermes_base_url=url,
                    ),
                )
                self.assertIn(
                    "Mini App Hermes base URL must be loopback HTTP",
                    configured.validation_errors(),
                )

    def test_server_miniapp_requires_shared_redis(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config_path = Path(temporary) / "server.toml"
            config_path.write_text(
                """
[node]
profile = "server"

[events]
backend = "memory"

[miniapp]
enabled = true
""".strip(),
                encoding="utf-8",
            )
            settings = NodeSettings.load(
                config_path,
                env={"CLINK_HOME": temporary},
            )

        self.assertIn(
            "Server Mini App requires shared Redis",
            settings.validation_errors(),
        )

    def test_server_profile_requires_real_infrastructure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            settings = NodeSettings.defaults(
                Profile.SERVER,
                paths=NodePaths.from_home(Path(temporary)),
            )

        self.assertEqual(settings.storage.backend, StorageBackend.POSTGRES)
        self.assertEqual(settings.events.backend, EventBackend.REDIS)
        self.assertEqual(settings.secrets.backend, SecretBackend.VAULT)
        self.assertTrue(settings.multi_tenant)
        self.assertEqual(
            settings.validation_errors(),
            [
                "postgres storage requires CLINK_DATABASE_URL",
                "redis event backend requires CLINK_REDIS_URL",
                "vault secret backend requires CLINK_VAULT_ADDR",
                "vault secret backend requires CLINK_VAULT_TOKEN",
                "self_hosted interaction mode requires "
                "CLINK_PUBLIC_BASE_URL",
            ],
        )

    def test_environment_completes_server_profile(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            settings = NodeSettings.load(
                env={
                    "CLINK_HOME": temporary,
                    "CLINK_PROFILE": "server",
                    "CLINK_DATABASE_URL": "postgresql://clink@db/clink",
                    "CLINK_REDIS_URL": "redis://redis/0",
                    "CLINK_PUBLIC_BASE_URL": "https://node.example.test",
                    "CLINK_VAULT_ADDR": "https://vault.example.test",
                    "CLINK_VAULT_TOKEN": "vault-token",
                    "CLINK_MODULE_MARKETPLACE_MODE": "external",
                    "CLINK_MODULE_MARKETPLACE_URL": "http://marketplace:8050",
                    "CLINK_MODULE_MARKETPLACE_MCP_URL": (
                        "http://marketplace:9050/mcp"
                    ),
                }
            )

        self.assertEqual(settings.validation_errors(), [])
        self.assertEqual(
            settings.modules["marketplace"].mode,
            ModuleMode.EXTERNAL,
        )
        self.assertEqual(
            settings.modules["marketplace"].endpoint,
            "http://marketplace:8050",
        )
        self.assertEqual(
            settings.secrets.vault_address,
            "https://vault.example.test",
        )

    def test_environment_configures_prediction_account_binding_service(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            settings = NodeSettings.load(
                env={
                    "CLINK_HOME": temporary,
                    "CLINK_PREDICTION_MARKETS_ACCOUNT_BINDING_SERVICE_URL": (
                        "http://prediction-binding:8047"
                    ),
                    "CLINK_PREDICTION_MARKETS_DEPOSIT_WALLET_SERVICE_URL": (
                        "http://prediction-deposit:8048"
                    ),
                }
            )

        self.assertEqual(
            settings.modules[
                "prediction-markets"
            ].service_urls["account_binding"],
            "http://prediction-binding:8047",
        )
        self.assertEqual(
            settings.modules[
                "prediction-markets"
            ].service_urls.get("deposit_wallet"),
            "http://prediction-deposit:8048",
        )

    def test_prediction_deposit_wallet_service_url_is_validated(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            settings = NodeSettings.defaults(
                Profile.PERSONAL,
                paths=NodePaths.from_home(Path(temporary)),
            )
        prediction = settings.modules["prediction-markets"]
        settings = replace(
            settings,
            modules={
                **settings.modules,
                "prediction-markets": replace(
                    prediction,
                    service_urls={"deposit_wallet": "file:///tmp/wallet"},
                ),
            },
        )

        self.assertIn(
            "Prediction Markets deposit wallet service URL is invalid",
            settings.validation_errors(),
        )

    def test_server_example_covers_all_external_services(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            settings = NodeSettings.load(
                ROOT / "clink.node.server.example.toml",
                env={
                    "CLINK_HOME": temporary,
                    "CLINK_DATABASE_URL": (
                        "postgresql+psycopg://clink:secret@db/clink"
                    ),
                    "CLINK_REDIS_URL": "redis://redis:6379/0",
                    "CLINK_VAULT_ADDR": "https://vault.example.test",
                    "CLINK_VAULT_TOKEN": "vault-token",
                    "CLINK_PUBLIC_BASE_URL": "https://clink.example.test",
                },
            )

        self.assertEqual(settings.validation_errors(), [])
        self.assertTrue(settings.multi_tenant)
        self.assertEqual(
            settings.modules["core"].service_urls["funding"],
            "http://core:8018",
        )
        self.assertEqual(
            settings.modules[
                "prediction-markets"
            ].service_urls["account_binding"],
            "http://prediction-markets:8047",
        )

    def test_external_module_without_endpoint_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            settings = NodeSettings.load(
                env={
                    "CLINK_HOME": temporary,
                    "CLINK_MODULE_CORE_MODE": "external",
                }
            )

        self.assertIn(
            "external module core requires an endpoint",
            settings.validation_errors(),
        )

    def test_redacted_config_does_not_include_database_url(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            settings = NodeSettings.load(
                env={
                    "CLINK_HOME": temporary,
                    "CLINK_PROFILE": "server",
                    "CLINK_DATABASE_URL": (
                        "postgresql://user:top-secret@db/clink"
                    ),
                    "CLINK_REDIS_URL": "redis://:secret@redis/0",
                    "CLINK_PUBLIC_BASE_URL": "https://node.example.test",
                    "CLINK_VAULT_ADDR": "https://vault.example.test",
                    "CLINK_VAULT_TOKEN": "vault-token",
                }
            )

        redacted = repr(settings.redacted())
        self.assertNotIn("top-secret", redacted)
        self.assertNotIn("redis://", redacted)
        self.assertNotIn("vault-token", redacted)


if __name__ == "__main__":
    unittest.main()
