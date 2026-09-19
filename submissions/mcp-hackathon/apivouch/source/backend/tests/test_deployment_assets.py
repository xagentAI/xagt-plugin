"""Static safety contracts complement (not replace) Docker/Caddy runtime checks."""

import importlib.util
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def test_vps_network_and_production_contract():
    compose = yaml.safe_load((ROOT / "deploy/vps/docker-compose.yml").read_text())
    services = compose["services"]
    assert {name for name, service in services.items() if "ports" in service} == {"caddy"}
    assert services["caddy"]["ports"] == ["80:80", "443:443"]
    assert services["db"]["networks"] == ["database"]
    assert compose["networks"]["database"]["internal"] is True
    assert not compose["networks"]["edge"].get("internal", False)
    assert services["app"]["networks"] == ["edge", "database"]
    assert services["app"]["user"] == "10001:10001"
    env = services["app"]["environment"]
    assert env["ALLOW_PRIVATE_NETWORK"] == "false"
    assert env["REQUIRE_SIGNED_RECEIPTS"] == "true"
    for name in ("GIT_COMMIT", "PUBLIC_BASE_URL", "RECEIPT_SIGNING_PRIVATE_KEY_B64"):
        assert "${" + name + ":?" in env[name]
    assert services["db"]["volumes"] == ["postgres_data:/var/lib/postgresql/data"]
    for service in services.values():
        assert service["restart"] == "unless-stopped"
        assert service["logging"]["options"] == {"max-size": "10m", "max-file": "3"}
        assert service["healthcheck"]["timeout"] == "5s"


def test_secret_scanner_rules_and_safe_output(monkeypatch, capsys):
    spec = importlib.util.spec_from_file_location("scanner", ROOT / "scripts/scan_secrets.py")
    scanner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(scanner)
    key = b"A" * 43 + b"="
    assert scanner.RULES["signing-key-literal"].search(b"RECEIPT_SIGNING_PRIVATE_KEY_B64=" + key)
    assert scanner.RULES["private-key"].search(b"-----BEGIN " + b"PRIVATE KEY-----")
    assert not scanner.RULES["signing-key-literal"].search(b"RECEIPT_SIGNING_PRIVATE_KEY_B64=${KEY}")
    fixture = next(iter(scanner.TEST_URLS["backend/tests/test_core.py"]))
    assert scanner.RULES["credential-url"].search(fixture).group() == fixture
    assert fixture.replace(b"pass", b"different") not in scanner.TEST_URLS["backend/tests/test_core.py"]
    assert scanner.RULES["credential-url"].search(fixture.replace(b"pass", b"different"))
    monkeypatch.setattr(scanner, "scan", lambda root: [("example.txt", 1, "signing-key-literal")])
    assert scanner.main() == 1
    output = capsys.readouterr().out
    assert key.decode() not in output
    assert "example.txt:1: signing-key-literal" in output
