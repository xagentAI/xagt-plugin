from __future__ import annotations

from dataclasses import replace

import pytest

from apps.node.clink_node.config import NodeSettings, OpcSettings, Profile
from apps.node.clink_node.paths import NodePaths


def test_opc_is_opt_in_and_is_safe_to_show_in_redacted_config(tmp_path):
    settings = NodeSettings.defaults(paths=NodePaths.from_home(tmp_path))
    assert settings.opc == OpcSettings()
    assert settings.redacted()["opc"] == {"enabled": False}


def test_opc_environment_requires_server_boundary_and_loads_public_origin(tmp_path):
    settings = NodeSettings.load(
        env={
            "CLINK_PROFILE": "server",
            "CLINK_OPC_ENABLED": "true",
            "CLINK_OPC_PUBLIC_ORIGIN": "https://opc.example",
        },
        paths=NodePaths.from_home(tmp_path),
    )
    assert settings.opc.enabled is True
    assert settings.opc.public_origin == "https://opc.example"
    assert not any("OPC public origin" in error for error in settings.validation_errors())

    personal = replace(settings, profile=Profile.PERSONAL, multi_tenant=False)
    assert "OPC requires the multi-tenant Server Profile" in personal.validation_errors()


@pytest.mark.parametrize(
    "origin",
    (
        "http://opc.example",
        "https://user:password@opc.example",
        "https://opc.example/path",
        "https://opc.example?token=secret",
        "https://opc.example#fragment",
    ),
)
def test_opc_rejects_unsafe_public_origin(tmp_path, origin):
    settings = NodeSettings.load(
        env={
            "CLINK_PROFILE": "server",
            "CLINK_OPC_ENABLED": "true",
            "CLINK_OPC_PUBLIC_ORIGIN": origin,
        },
        paths=NodePaths.from_home(tmp_path),
    )
    assert "OPC requires an HTTPS public origin without credentials, path, query or fragment" in settings.validation_errors()


def test_opc_document_rejects_unknown_setting(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(
        "[opc]\nenabled = true\npublic_origin = 'https://opc.example'\nunknown = true\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="unknown OPC setting"):
        NodeSettings.load(path, env={}, paths=NodePaths.from_home(tmp_path))
