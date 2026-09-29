from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from clink_node.application import assemble_node
from clink_node.cli import main
from clink_node.config import (
    EventBackend,
    InteractionMode,
    ModuleMode,
    NodeSettings,
    Profile,
    SecretBackend,
    StorageBackend,
)
from clink_node.secrets import MemorySecretStore


ROOT = Path(__file__).resolve().parents[2]


class NodeProfileEndToEndTests(unittest.TestCase):
    def test_personal_profile_bootstraps_one_local_node(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary) / ".clink"
            with patch.dict(
                "os.environ",
                {"CLINK_HOME": str(home)},
                clear=True,
            ):
                self.assertEqual(
                    main(["init", "--profile", "personal"]),
                    0,
                )
                settings = NodeSettings.load()

            assembly = assemble_node(
                settings,
                secret_store=MemorySecretStore({}),
            )
            client = TestClient(assembly.api_application)

            self.assertEqual(settings.profile, Profile.PERSONAL)
            self.assertEqual(
                settings.storage.backend,
                StorageBackend.SQLITE,
            )
            self.assertEqual(settings.events.backend, EventBackend.MEMORY)
            self.assertEqual(
                settings.secrets.backend,
                SecretBackend.KEYCHAIN,
            )
            self.assertEqual(
                settings.interaction.mode,
                InteractionMode.LOCAL,
            )
            self.assertEqual(settings.validation_errors(), [])
            self.assertTrue(settings.storage.sqlite_path.is_file())
            self.assertEqual(client.get("/healthz").status_code, 200)
            homepage = client.get("/").text
            self.assertIn("Agentonomy", homepage)
            self.assertNotIn("Clink", homepage)
            self.assertEqual(
                assembly.repository.path,
                settings.storage.sqlite_path,
            )
            self.assertEqual(
                set(assembly.mcp_proxy.downstreams),
                {"marketplace", "prediction-markets"},
            )

    def test_server_profile_describes_one_external_control_plane(self) -> None:
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

        self.assertEqual(settings.profile, Profile.SERVER)
        self.assertEqual(settings.validation_errors(), [])
        self.assertEqual(
            settings.storage.backend,
            StorageBackend.POSTGRES,
        )
        self.assertEqual(settings.events.backend, EventBackend.REDIS)
        self.assertEqual(settings.secrets.backend, SecretBackend.VAULT)
        self.assertEqual(
            settings.interaction.mode,
            InteractionMode.SELF_HOSTED,
        )
        self.assertTrue(settings.multi_tenant)
        self.assertEqual(
            {module.mode for module in settings.modules.values()},
            {ModuleMode.EXTERNAL},
        )
        self.assertEqual(
            settings.modules["core"].service_urls["policy"],
            "http://core:8015",
        )
        self.assertEqual(
            settings.modules[
                "prediction-markets"
            ].service_urls["account_binding"],
            "http://prediction-markets:8047",
        )


if __name__ == "__main__":
    unittest.main()
