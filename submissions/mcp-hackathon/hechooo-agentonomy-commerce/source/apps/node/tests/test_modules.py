from __future__ import annotations

from dataclasses import replace
import tempfile
import unittest
from pathlib import Path

from apps.node.clink_node.config import (
    ModuleMode,
    ModuleSettings,
    NodeSettings,
    Profile,
)
from apps.node.clink_node.modules import default_module_definitions
from apps.node.clink_node.paths import NodePaths


class ModuleDefinitionTests(unittest.TestCase):
    def test_managed_marketplace_uses_liveness_for_process_startup(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            settings = NodeSettings.defaults(
                Profile.PERSONAL,
                paths=NodePaths.from_home(Path(tmpdir) / ".clink"),
            )
            modules = {
                item.name: item
                for item in default_module_definitions(
                    Path("/workspace"),
                    settings,
                )
            }

        self.assertEqual(
            modules["marketplace"].health_urls,
            ("http://127.0.0.1:8050/livez",),
        )
        self.assertEqual(
            modules["marketplace"].readiness_urls,
            ("http://127.0.0.1:8050/healthz",),
        )

    def test_prediction_markets_runtime_readiness_covers_required_services(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            settings = NodeSettings.defaults(
                Profile.PERSONAL,
                paths=NodePaths.from_home(Path(tmpdir) / ".clink"),
            )
            modules = {
                item.name: item
                for item in default_module_definitions(
                    Path("/workspace"),
                    settings,
                )
            }

        self.assertEqual(
            modules["prediction-markets"].health_urls,
            ("http://127.0.0.1:8040/healthz",),
        )
        self.assertEqual(
            modules["prediction-markets"].readiness_urls,
            tuple(
                f"http://127.0.0.1:{port}/healthz"
                for port in (8040, 8041, 8042, 8043, 8044, 8045, 8046, 8047, 8048)
            ),
        )

    def test_external_modules_keep_aggregate_health_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            settings = NodeSettings.defaults(
                Profile.PERSONAL,
                paths=NodePaths.from_home(Path(tmpdir) / ".clink"),
            )
            settings = replace(
                settings,
                modules={
                    **settings.modules,
                    "marketplace": ModuleSettings(
                        mode=ModuleMode.EXTERNAL,
                        endpoint="http://marketplace.example:8050",
                    ),
                    "prediction-markets": ModuleSettings(
                        mode=ModuleMode.EXTERNAL,
                        endpoint="http://prediction.example:8040",
                    ),
                },
            )
            modules = {
                item.name: item
                for item in default_module_definitions(
                    Path("/workspace"),
                    settings,
                )
            }

        self.assertEqual(
            modules["marketplace"].health_urls,
            ("http://marketplace.example:8050/livez",),
        )
        self.assertEqual(modules["marketplace"].readiness_urls, ())
        self.assertEqual(
            modules["prediction-markets"].health_urls,
            ("http://prediction.example:8040/healthz",),
        )
        self.assertEqual(modules["prediction-markets"].readiness_urls, ())

    def test_managed_prediction_markets_use_custom_service_urls(self) -> None:
        custom_urls = {
            "router": "http://ignored-router.example:18040",
            "preview": "http://preview.example:18041",
            "execution": "http://execution.example:18042",
            "context": "http://ignored-context.example:18043",
            "portfolio": "http://ignored-portfolio.example:18044",
            "sync": "http://ignored-sync.example:18045",
            "funding": "http://funding.example:18046",
            "account_binding": "http://binding.example:18047",
            "deposit_wallet": "http://deposit.example:18048",
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            settings = NodeSettings.defaults(
                Profile.PERSONAL,
                paths=NodePaths.from_home(Path(tmpdir) / ".clink"),
            )
            prediction = settings.modules["prediction-markets"]
            settings = replace(
                settings,
                modules={
                    **settings.modules,
                    "prediction-markets": replace(
                        prediction,
                        endpoint="http://router.example:18040",
                        service_urls=custom_urls,
                    ),
                },
            )
            modules = {
                item.name: item
                for item in default_module_definitions(
                    Path("/workspace"),
                    settings,
                )
            }

        self.assertEqual(
            modules["prediction-markets"].readiness_urls,
            (
                "http://router.example:18040/healthz",
                "http://preview.example:18041/healthz",
                "http://execution.example:18042/healthz",
                "http://127.0.0.1:8043/healthz",
                "http://127.0.0.1:8044/healthz",
                "http://127.0.0.1:8045/healthz",
                "http://funding.example:18046/healthz",
                "http://binding.example:18047/healthz",
                "http://deposit.example:18048/healthz",
            ),
        )


if __name__ == "__main__":
    unittest.main()
