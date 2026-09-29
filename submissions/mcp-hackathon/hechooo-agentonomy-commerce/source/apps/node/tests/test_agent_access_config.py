from dataclasses import replace

import pytest

from apps.node.clink_node.config import NodeSettings, Profile
from apps.node.clink_node.paths import NodePaths


def test_agent_access_is_opt_in_and_contains_no_credentials(tmp_path):
    settings = NodeSettings.defaults(paths=NodePaths.from_home(tmp_path))
    assert settings.agent_access.enabled is False
    assert settings.redacted()["agent_access"] == {"enabled": False}


def test_agent_access_environment_loads_and_requires_server_boundary(tmp_path):
    settings = NodeSettings.load(env={
        "CLINK_NODE_HOME": str(tmp_path),
        "CLINK_AGENT_ACCESS_ENABLED": "true",
        "CLINK_AGENT_ACCESS_ISSUER": "wallet-service",
        "CLINK_AGENT_ACCESS_MCP_PUBLIC_URL": "https://agents.example/mcp",
    }, paths=NodePaths.from_home(tmp_path))
    assert settings.agent_access.issuer == "wallet-service"
    assert "agent access requires the multi-tenant Server Profile" in settings.validation_errors()
    server = replace(settings, profile=Profile.SERVER, multi_tenant=True)
    assert not any("agent access" in error for error in server.validation_errors())
    assert "control_token" not in str(server.redacted())


@pytest.mark.parametrize("document", [
    '[agent_access]\nenabled = "yes"\n',
    '[agent_access]\nenabled = true\nunknown = 1\n',
])
def test_agent_access_rejects_ambiguous_configuration(tmp_path, document):
    path = tmp_path / "config.toml"
    path.write_text(document)
    with pytest.raises(ValueError):
        NodeSettings.load(path, env={}, paths=NodePaths.from_home(tmp_path))


@pytest.mark.parametrize("url", [
    "http://agents.example/mcp", "https://user:password@agents.example/mcp",
    "https://agents.example/mcp?token=secret", "https://agents.example/mcp#part",
    "https://agents.example:invalid/mcp", "https://agents.example:999999/mcp",
])
def test_agent_access_rejects_unsafe_public_mcp_url(tmp_path, url):
    settings = NodeSettings.load(env={
        "CLINK_PROFILE": "server",
        "CLINK_AGENT_ACCESS_ENABLED": "true",
        "CLINK_AGENT_ACCESS_ISSUER": "wallet-service",
        "CLINK_AGENT_ACCESS_MCP_PUBLIC_URL": url,
    }, paths=NodePaths.from_home(tmp_path))
    assert "agent access requires an HTTPS MCP URL without credentials, query or fragment" in settings.validation_errors()
