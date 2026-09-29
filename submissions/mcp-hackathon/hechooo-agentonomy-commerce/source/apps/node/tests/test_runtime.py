from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
import sys

from apps.node.clink_node.config import (
    EventBackend,
    EventSettings,
    InteractionMode,
    InteractionSettings,
    NodeSettings,
    Profile,
    StorageBackend,
    StorageSettings,
)
from apps.node.clink_node.paths import NodePaths
from apps.node.clink_node.runtime import ManagedEnvironmentBuilder
from apps.node.clink_node.secrets import MemorySecretStore


class ManagedRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.paths = NodePaths.from_home(root / ".clink")
        self.settings = NodeSettings.defaults(
            Profile.PERSONAL,
            paths=self.paths,
        )
        self.secrets = MemorySecretStore({})

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_personal_environment_uses_one_local_database(self) -> None:
        env = ManagedEnvironmentBuilder(
            self.settings,
            self.secrets,
            base_env={"PATH": "/usr/bin"},
        ).build()
        database_path = str(self.paths.data / "clink.db")

        self.assertEqual(env["CLINK_NODE_MANAGED"], "1")
        self.assertIn(database_path, env["CLINK_FUNDING_DATABASE_URL"])
        self.assertIn(database_path, env["MARKETPLACE_DATABASE_URL"])
        self.assertEqual(
            env["PREDICTION_MARKETS_LEDGER_DB_FILE"],
            database_path,
        )
        self.assertEqual(env["MARKETPLACE_REDIS_URL"], "")
        self.assertEqual(env["REDIS_URL"], "")

    def test_internal_secrets_are_generated_once_and_shared(self) -> None:
        builder = ManagedEnvironmentBuilder(
            self.settings,
            self.secrets,
            base_env={},
        )

        first = builder.build()
        second = builder.build()

        self.assertEqual(
            first["CLINK_CORE_INTERNAL_API_TOKEN"],
            second["CLINK_CORE_INTERNAL_API_TOKEN"],
        )
        self.assertEqual(
            first["CLINK_CORE_INTERNAL_API_TOKEN"],
            first["PREDICTION_MARKETS_CORE_INTERNAL_API_TOKEN"],
        )
        self.assertNotEqual(
            first["CLINK_CORE_INTERNAL_API_TOKEN"],
            first["CLINK_RECEIPT_SIGNING_KEY"],
        )
        self.assertGreaterEqual(
            len(first["CLINK_CORE_INTERNAL_API_TOKEN"]),
            43,
        )

    def test_personal_runtime_is_loopback_and_live_money_is_off(self) -> None:
        env = ManagedEnvironmentBuilder(
            self.settings,
            self.secrets,
            base_env={},
        ).build()

        self.assertEqual(env["ACCOUNT_SERVICE_HOST"], "127.0.0.1")
        self.assertEqual(env["MARKETPLACE_REGISTRY_HOST"], "127.0.0.1")
        self.assertEqual(
            env["PREDICTION_MARKETS_EXECUTION_HOST"],
            "127.0.0.1",
        )
        self.assertEqual(env["CLINK_LIVE_FUNDING"], "false")
        self.assertEqual(env["CLINK_RISK_PROVIDER"], "misttrack")
        self.assertEqual(env["CLINK_RISK_MODE"], "shadow")
        self.assertEqual(env["PREDICTION_MARKETS_LIVE_MODE"], "false")
        self.assertEqual(
            env["CLINK_ACCOUNT_PUBLIC_BASE_URL"],
            "http://127.0.0.1:8170",
        )
        self.assertEqual(
            env["MARKETPLACE_PUBLIC_BASE_URL"],
            "http://127.0.0.1:8170",
        )
        self.assertEqual(
            env["PREDICTION_MARKETS_ACCOUNT_BINDING_CONSOLE_BASE_URL"],
            "http://127.0.0.1:8170",
        )
        self.assertEqual(
            env["PREDICTION_MARKETS_EXECUTION_CONSOLE_BASE_URL"],
            "http://127.0.0.1:8170",
        )
        self.assertNotIn(
            "CLINK_NATIVE_FACILITATOR_RELAYER_PRIVATE_KEY",
            env,
        )

    def test_explicit_operator_live_money_settings_are_preserved(self) -> None:
        env = ManagedEnvironmentBuilder(
            self.settings,
            self.secrets,
            base_env={
                "CLINK_LIVE_FUNDING": "true",
                "CLINK_NATIVE_FACILITATOR_ENABLED": "true",
                "CLINK_RISK_PROVIDER": "misttrack",
                "CLINK_RISK_MODE": "enforce",
                "MISTTRACK_API_KEY": "operator-test-key",
                "MISTTRACK_TIMEOUT_SECONDS": "3.5",
                "MISTTRACK_MAX_ATTEMPTS": "3",
                "CLINK_RISK_HOLD_SCORE": "20",
                "CLINK_RISK_DENY_SCORE": "60",
                "CLINK_RISK_MAX_AGE_SECONDS": "120",
                "CLINK_RISK_CACHE_TTL_SECONDS": "60",
                "PREDICTION_MARKETS_LIVE_MODE": "true",
            },
        ).build()

        self.assertEqual(env["CLINK_LIVE_FUNDING"], "true")
        self.assertEqual(
            env["CLINK_NATIVE_FACILITATOR_ENABLED"],
            "true",
        )
        self.assertEqual(env["CLINK_RISK_PROVIDER"], "misttrack")
        self.assertEqual(env["CLINK_RISK_MODE"], "enforce")
        self.assertEqual(env["MISTTRACK_API_KEY"], "operator-test-key")
        self.assertEqual(env["MISTTRACK_TIMEOUT_SECONDS"], "3.5")
        self.assertEqual(env["MISTTRACK_MAX_ATTEMPTS"], "3")
        self.assertEqual(env["CLINK_RISK_HOLD_SCORE"], "20")
        self.assertEqual(env["CLINK_RISK_DENY_SCORE"], "60")
        self.assertEqual(env["CLINK_RISK_MAX_AGE_SECONDS"], "120")
        self.assertEqual(env["CLINK_RISK_CACHE_TTL_SECONDS"], "60")
        self.assertEqual(env["PREDICTION_MARKETS_LIVE_MODE"], "true")

    def test_managed_environment_removes_all_legacy_risk_variables(self) -> None:
        env = ManagedEnvironmentBuilder(
            self.settings,
            self.secrets,
            base_env={
                "CREDITMODEL_BASE_URL": "https://legacy.example",
                "CREDITMODEL_API_KEY": "legacy-secret",
                "CREDITMODEL_MODE": "enforce",
                "CREDITMODEL_TIMEOUT_SECONDS": "99",
            },
        ).build()

        self.assertFalse(any(name.startswith("CREDITMODEL_") for name in env))

    def test_misttrack_key_is_only_inherited_from_parent_environment(self) -> None:
        without_key = ManagedEnvironmentBuilder(
            self.settings,
            self.secrets,
            base_env={},
        ).build()
        with_key = ManagedEnvironmentBuilder(
            self.settings,
            self.secrets,
            base_env={"MISTTRACK_API_KEY": "operator-test-key"},
        ).build()

        self.assertNotIn("MISTTRACK_API_KEY", without_key)
        self.assertEqual(with_key["MISTTRACK_API_KEY"], "operator-test-key")
        self.assertNotIn("misttrack", repr(self.settings).lower())
        self.assertFalse(any("misttrack" in name for name in self.secrets.values))

    def test_managed_modules_use_the_node_python_environment(self) -> None:
        env = ManagedEnvironmentBuilder(
            self.settings,
            self.secrets,
            base_env={"PATH": "/usr/bin"},
        ).build()

        self.assertEqual(env["PYTHON_BIN"], sys.executable)
        self.assertEqual(
            env["PATH"].split(":", 1)[0],
            str(Path(sys.executable).parent),
        )

    def test_managed_server_core_receives_profile_and_shared_redis(self) -> None:
        settings = replace(
            NodeSettings.defaults(Profile.SERVER, paths=self.paths),
            storage=StorageSettings(
                backend=StorageBackend.POSTGRES,
                postgres_url="postgresql://clink:test@db.example/clink",
            ),
            events=EventSettings(
                backend=EventBackend.REDIS,
                redis_url="rediss://redis.example:6380/0",
            ),
            interaction=InteractionSettings(
                mode=InteractionMode.SELF_HOSTED,
                public_base_url="https://clink.example",
            ),
        )

        env = ManagedEnvironmentBuilder(
            settings,
            self.secrets,
            base_env={"PATH": "/usr/bin"},
        ).build()

        self.assertEqual(env["CLINK_PROFILE"], "server")
        self.assertEqual(
            env["CLINK_REDIS_URL"],
            "rediss://redis.example:6380/0",
        )


if __name__ == "__main__":
    unittest.main()
