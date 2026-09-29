from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from apps.node.clink_node.agent_access_mcp import AgentScopedMcpProxy
from apps.node.clink_node.application import assemble_node
from apps.node.clink_node.config import (
    EventBackend,
    EventSettings,
    InteractionMode,
    InteractionSettings,
    ModuleMode,
    NodeSettings,
    OpcSettings,
    Profile,
    SecretBackend,
    SecretSettings,
    StorageBackend,
    StorageSettings,
)
from apps.node.clink_node.paths import NodePaths
from apps.node.clink_node.secrets import MemorySecretStore
from apps.node.clink_node.storage.postgres import PostgresNodeRepository


def test_opc_only_assembly_uses_scoped_mcp_and_public_opc_routes(tmp_path: Path):
    defaults = NodeSettings.defaults(
        Profile.SERVER,
        paths=NodePaths.from_home(tmp_path / ".clink"),
    )
    modules = dict(defaults.modules)
    modules["prediction-markets"] = replace(
        modules["prediction-markets"], mode=ModuleMode.DISABLED
    )
    settings = replace(
        defaults,
        storage=StorageSettings(
            backend=StorageBackend.POSTGRES,
            postgres_url=f"sqlite+pysqlite:///{tmp_path / 'node.sqlite3'}",
        ),
        events=EventSettings(backend=EventBackend.MEMORY),
        secrets=SecretSettings(backend=SecretBackend.KEYCHAIN),
        interaction=InteractionSettings(
            mode=InteractionMode.SELF_HOSTED,
            public_base_url="https://node.example",
        ),
        modules=modules,
        opc=OpcSettings(enabled=True, public_origin="https://opc.example"),
    )
    repository = PostgresNodeRepository(settings.storage.postgres_url or "")
    assembly = assemble_node(
        settings,
        secret_store=MemorySecretStore({}),
        repository=repository,
    )
    try:
        assert isinstance(assembly.mcp_proxy, AgentScopedMcpProxy)
        assert assembly.context.agent_access_service is None
        paths = set()
        for route in assembly.api_application.routes:
            path = getattr(route, "path", "")
            if path.startswith("/v1/opc/"):
                paths.add(path)
            # FastAPI 0.139 keeps included routers as lazy wrapper routes;
            # inspect the original router so this assertion covers both
            # eager and lazy FastAPI versions.
            nested = getattr(route, "original_router", None)
            for child in getattr(nested, "routes", ()):
                child_path = getattr(child, "path", "")
                if child_path.startswith("/v1/opc/"):
                    paths.add(child_path)
        assert paths == {
            "/v1/opc/pairings",
            "/v1/opc/token",
            "/v1/opc/status",
            "/v1/opc/revoke",
        }
    finally:
        for closer in reversed(assembly.resource_closers):
            closer()
        assembly.release_lifecycle_locks()
        repository.engine.dispose()
