from __future__ import annotations

import asyncio
import base64
import json
import stat
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import httpx
import pytest

from clink_node.opc_client import OpcClient, OpcClientError, OpcClientStateStore
from clink_node import opc_cli
from shared.opc_protocol import verify_opc_proof


ORIGIN = "https://agentonomy.example"
ACCOUNT_ORIGIN = "https://account.agentonomy.example"
NOW = 1_788_451_200


def _json_request(request: httpx.Request) -> dict[str, object]:
    return json.loads(request.content.decode("utf-8"))


def _request_id(request: httpx.Request, *, action: str, now: int = NOW) -> str:
    proof = _json_request(request)["proof"]
    return verify_opc_proof(
        proof,
        origin=ORIGIN,
        action=action,
        now=now,
    )["request_id"]


def _action_response(action: str, installation: str) -> httpx.Response:
    if action == "pair":
        return httpx.Response(
            201,
            json={
                "installation_id": installation,
                "pairing_id": "pairing-1",
                "verification_uri": f"{ORIGIN}/account/opc/pairing-1",
                "expires_at": NOW + 600,
                "status": "pending",
            },
        )
    if action == "token":
        return httpx.Response(
            200,
            json={
                "installation_id": installation,
                "access_token": "opc-token-recovered",
                "token_type": "Bearer",
                "expires_at": NOW + 300,
                "mcp_url": f"{ORIGIN}/mcp",
            },
        )
    if action == "revoke":
        return httpx.Response(
            200,
            json={"installation_id": installation, "status": "revoked"},
        )
    return httpx.Response(
        200,
        json={"installation_id": installation, "status": "pending"},
    )


def _invoke_action(client: OpcClient, action: str):
    if action == "pair":
        return client.connect()
    if action == "token":
        return client.access_token()
    if action == "revoke":
        return client.revoke()
    return client.status()


def test_opc_client_persists_only_identity_and_renews_token_in_memory(tmp_path) -> None:
    calls: list[tuple[str, dict[str, object]]] = []
    now = [1_788_451_200]

    def handler(request: httpx.Request) -> httpx.Response:
        body = _json_request(request)
        calls.append((request.url.path, body))
        if request.url.path == "/v1/opc/pairings":
            return httpx.Response(
                201,
                json={
                    "installation_id": store.load().installation_id,
                    "pairing_id": "pairing-1",
                    "verification_uri": f"{ORIGIN}/account/opc/pairing-1",
                    "expires_at": now[0] + 600,
                    "status": "pending",
                },
            )
        if request.url.path == "/v1/opc/token":
            sequence = sum(path == "/v1/opc/token" for path, _ in calls)
            return httpx.Response(
                200,
                json={
                    "installation_id": store.load().installation_id,
                    "access_token": f"opc-token-{sequence}",
                    "token_type": "Bearer",
                    "expires_at": now[0] + 300,
                    "mcp_url": f"{ORIGIN}/mcp",
                },
            )
        raise AssertionError(request.url.path)

    store = OpcClientStateStore(tmp_path / "opc-client.json")
    first = OpcClient(
        store,
        origin=ORIGIN,
        label="Office Linux",
        clock=lambda: now[0],
        transport=httpx.MockTransport(handler),
    )
    pairing = first.connect()
    first_id = first.state.installation_id
    assert pairing["status"] == "pending"
    assert stat.S_IMODE(store.path.stat().st_mode) == 0o600
    serialized = store.path.read_text(encoding="utf-8")
    assert "opc-token" not in serialized

    restarted = OpcClient(
        store,
        clock=lambda: now[0],
        transport=httpx.MockTransport(handler),
    )
    assert restarted.state.installation_id == first_id
    assert restarted.access_token() == "opc-token-1"
    now[0] += 241
    assert restarted.access_token() == "opc-token-2"
    assert "opc-token" not in store.path.read_text(encoding="utf-8")


def test_opc_client_accepts_token_ttl_within_protocol_clock_skew(tmp_path) -> None:
    store = OpcClientStateStore(tmp_path / "opc-client.json")
    store.create(origin=ORIGIN, label="Linux")

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "installation_id": store.load().installation_id,
                "access_token": "opc-token-clock-skew",
                "token_type": "Bearer",
                "expires_at": NOW + 330,
                "mcp_url": f"{ORIGIN}/mcp",
            },
        )

    client = OpcClient(
        store,
        clock=lambda: NOW,
        transport=httpx.MockTransport(handler),
    )
    try:
        assert client.access_token() == "opc-token-clock-skew"
    finally:
        client.close()


def test_opc_client_rejects_token_ttl_beyond_protocol_clock_skew(tmp_path) -> None:
    store = OpcClientStateStore(tmp_path / "opc-client.json")
    store.create(origin=ORIGIN, label="Linux")

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "installation_id": store.load().installation_id,
                "access_token": "opc-token-too-long",
                "token_type": "Bearer",
                "expires_at": NOW + 331,
                "mcp_url": f"{ORIGIN}/mcp",
            },
        )

    client = OpcClient(
        store,
        clock=lambda: NOW,
        transport=httpx.MockTransport(handler),
    )
    try:
        with pytest.raises(OpcClientError, match="token response is invalid"):
            client.access_token()
    finally:
        client.close()


def test_opc_client_never_retries_a_failed_remote_tool_call(tmp_path) -> None:
    client = OpcClientStateStore(tmp_path / "opc-client.json").create(
        origin=ORIGIN,
        label="Linux",
    )
    calls = 0

    class FailingMcp:
        async def call_tool(self, name, arguments):
            nonlocal calls
            calls += 1
            raise RuntimeError("remote outcome unknown")

    opc = OpcClient.from_state(client, mcp_client_factory=lambda *_: FailingMcp())
    opc._access_token = "runtime-token"
    opc._access_token_expires_at = 9_999_999_999
    opc._mcp_url = f"{ORIGIN}/mcp"

    with pytest.raises(RuntimeError, match="unknown"):
        import anyio

        anyio.run(opc.call_tool, "execute_clink_purchase", {"request_id": "one"})
    assert calls == 1


def test_async_remote_mcp_setup_offloads_blocking_token_request(tmp_path) -> None:
    store = OpcClientStateStore(tmp_path / "opc-client.json")
    store.create(origin=ORIGIN, label="Linux")
    loop_thread = threading.get_ident()
    token_threads: list[int] = []
    remote_calls: list[tuple[str, dict[str, object]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/opc/token"
        token_threads.append(threading.get_ident())
        return httpx.Response(
            200,
            json={
                "installation_id": store.load().installation_id,
                "access_token": "opc-token-async",
                "token_type": "Bearer",
                "expires_at": NOW + 300,
                "mcp_url": f"{ORIGIN}/mcp",
            },
        )

    class Remote:
        async def list_tools(self):
            remote_calls.append(("list", {}))
            return []

        async def call_tool(self, name, arguments):
            remote_calls.append((name, arguments))
            return {"ok": True}

    client = OpcClient(
        store,
        clock=lambda: NOW,
        transport=httpx.MockTransport(handler),
        mcp_client_factory=lambda *_: Remote(),
    )

    async def invoke():
        listed = await client.list_tools()
        called = await client.call_tool("get_clink_account_readiness", {})
        return listed, called

    listed, called = asyncio.run(invoke())

    assert listed == []
    assert called == {"ok": True}
    assert token_threads and all(thread_id != loop_thread for thread_id in token_threads)
    assert len(token_threads) == 1
    assert remote_calls == [
        ("list", {}),
        ("get_clink_account_readiness", {}),
    ]


def test_opc_state_rejects_symlinks_and_permissive_files(tmp_path) -> None:
    target = tmp_path / "target.json"
    target.write_text("{}", encoding="utf-8")
    target.chmod(0o600)
    link = tmp_path / "link.json"
    link.symlink_to(target)
    with pytest.raises(PermissionError):
        OpcClientStateStore(link).load()

    store = OpcClientStateStore(tmp_path / "state.json")
    store.create(origin=ORIGIN, label="Linux")
    store.path.chmod(0o644)
    with pytest.raises(PermissionError):
        store.load()


def test_opc_client_rejects_a_pairing_link_for_another_installation(tmp_path) -> None:
    store = OpcClientStateStore(tmp_path / "opc-client.json")

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            201,
            json={
                "installation_id": "opc_" + "0" * 40,
                "pairing_id": "pairing-1",
                "verification_uri": f"{ORIGIN}/account/session",
                "expires_at": 1_788_451_800,
                "status": "pending",
            },
        )

    client = OpcClient(
        store,
        origin=ORIGIN,
        label="Linux",
        clock=lambda: 1_788_451_200,
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(Exception, match="pairing response"):
        client.connect()


def test_opc_client_accepts_a_separate_trusted_https_account_origin(tmp_path) -> None:
    store = OpcClientStateStore(tmp_path / "opc-client.json")

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            201,
            json={
                "installation_id": store.load().installation_id,
                "pairing_id": "pairing-1",
                "verification_uri": f"{ACCOUNT_ORIGIN}/account/opc/pairing-1",
                "expires_at": NOW + 600,
                "status": "pending",
            },
        )

    client = OpcClient(
        store,
        origin=ORIGIN,
        label="Linux",
        clock=lambda: NOW,
        transport=httpx.MockTransport(handler),
    )
    try:
        assert client.connect()["verification_uri"].startswith(ACCOUNT_ORIGIN)
    finally:
        client.close()


@pytest.mark.parametrize("action", ["pair", "token", "revoke", "status"])
def test_opc_action_reuses_persisted_request_after_lost_response(
    tmp_path, action
) -> None:
    store = OpcClientStateStore(tmp_path / "opc-client.json")
    request_ids: list[str] = []
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        request_ids.append(_request_id(request, action=action))
        journal = store.path.with_name(store.path.name + ".requests")
        assert journal.exists(), "request id must be durable before dispatch"
        assert action in json.loads(journal.read_text(encoding="utf-8"))
        if calls == 1:
            raise httpx.ReadError("response lost", request=request)
        return _action_response(action, store.load().installation_id)

    first = OpcClient(
        store,
        origin=ORIGIN,
        label="Linux",
        clock=lambda: NOW,
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(OpcClientError, match="unavailable"):
        _invoke_action(first, action)
    first.close()

    restarted = OpcClient(
        store,
        clock=lambda: NOW,
        transport=httpx.MockTransport(handler),
    )
    result = _invoke_action(restarted, action)
    restarted.close()

    assert result
    assert len(request_ids) == 2
    assert request_ids[0] == request_ids[1]
    journal = store.path.with_name(store.path.name + ".requests")
    assert stat.S_IMODE(journal.stat().st_mode) == 0o600
    assert json.loads(journal.read_text(encoding="utf-8")) == {}
    assert "opc-token-recovered" not in journal.read_text(encoding="utf-8")


def test_opc_action_keeps_request_id_until_response_is_validated(tmp_path) -> None:
    store = OpcClientStateStore(tmp_path / "opc-client.json")
    request_ids: list[str] = []

    def invalid_handler(request: httpx.Request) -> httpx.Response:
        request_ids.append(_request_id(request, action="status"))
        return httpx.Response(
            200,
            json={"installation_id": "opc_" + "0" * 40, "status": "pending"},
        )

    first = OpcClient(
        store,
        origin=ORIGIN,
        label="Linux",
        clock=lambda: NOW,
        transport=httpx.MockTransport(invalid_handler),
    )
    with pytest.raises(OpcClientError, match="status response"):
        first.status()
    first.close()

    def valid_handler(request: httpx.Request) -> httpx.Response:
        request_ids.append(_request_id(request, action="status"))
        return _action_response("status", store.load().installation_id)

    restarted = OpcClient(
        store,
        clock=lambda: NOW,
        transport=httpx.MockTransport(valid_handler),
    )
    assert restarted.status()["status"] == "pending"
    restarted.close()
    assert request_ids[0] == request_ids[1]


@pytest.mark.parametrize("action", ["pair", "token"])
def test_opc_expired_recovered_response_retires_request_without_automatic_retry(
    tmp_path, action
) -> None:
    store = OpcClientStateStore(tmp_path / "opc-client.json")
    now = [NOW]
    request_ids: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        request_ids.append(_request_id(request, action=action, now=now[0]))
        if len(request_ids) == 1:
            raise httpx.ReadError("response lost", request=request)
        result = _action_response(action, store.load().installation_id)
        body = json.loads(result.content.decode("utf-8"))
        body["expires_at"] = (
            NOW + 300 if len(request_ids) == 2 else now[0] + 300
        )
        return httpx.Response(result.status_code, json=body)

    first = OpcClient(
        store,
        origin=ORIGIN,
        label="Linux",
        clock=lambda: now[0],
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(OpcClientError, match="unavailable"):
        _invoke_action(first, action)
    first.close()

    now[0] = NOW + 901
    restarted = OpcClient(
        store,
        clock=lambda: now[0],
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(OpcClientError, match="expired"):
        _invoke_action(restarted, action)
    assert len(request_ids) == 2, "expired recovery must not retry automatically"
    journal = store.path.with_name(store.path.name + ".requests")
    assert json.loads(journal.read_text(encoding="utf-8")) == {}

    assert _invoke_action(restarted, action)
    restarted.close()
    assert request_ids[0] == request_ids[1]
    assert request_ids[2] != request_ids[1]


@pytest.mark.parametrize("action", ["pair", "token"])
def test_opc_expired_mismatched_response_does_not_retire_request(
    tmp_path, action
) -> None:
    store = OpcClientStateStore(tmp_path / "opc-client.json")
    now = NOW + 901

    def handler(_request: httpx.Request) -> httpx.Response:
        result = _action_response(action, "opc_" + "0" * 40)
        body = json.loads(result.content.decode("utf-8"))
        body["expires_at"] = NOW + 300
        return httpx.Response(result.status_code, json=body)

    client = OpcClient(
        store,
        origin=ORIGIN,
        label="Linux",
        clock=lambda: now,
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(OpcClientError, match="response is invalid"):
        _invoke_action(client, action)
    pending = store.pending_request_id(action)
    client.close()

    restarted = OpcClient(
        store,
        clock=lambda: now,
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(OpcClientError, match="response is invalid"):
        _invoke_action(restarted, action)
    assert store.pending_request_id(action) == pending
    restarted.close()


def test_opc_request_journal_fences_concurrent_writers_and_completion(tmp_path) -> None:
    store = OpcClientStateStore(tmp_path / "opc-client.json")
    store.create(origin=ORIGIN, label="Linux")

    with ThreadPoolExecutor(max_workers=8) as executor:
        request_ids = list(
            executor.map(lambda _index: store.pending_request_id("token"), range(32))
        )

    assert len(set(request_ids)) == 1
    request_id = request_ids[0]
    store.complete_request("token", "00000000-0000-4000-8000-000000000000")
    assert store.pending_request_id("token") == request_id
    store.complete_request("token", request_id)

    journal = store.path.with_name(store.path.name + ".requests")
    assert json.loads(journal.read_text(encoding="utf-8")) == {}


def test_opc_request_journal_rejects_symlink_before_dispatch(tmp_path) -> None:
    store = OpcClientStateStore(tmp_path / "opc-client.json")
    store.create(origin=ORIGIN, label="Linux")
    target = tmp_path / "attacker-controlled.json"
    target.write_text("{}", encoding="utf-8")
    target.chmod(0o600)
    store.path.with_name(store.path.name + ".requests").symlink_to(target)

    def handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("unsafe journal must fail before dispatch")

    client = OpcClient(
        store,
        clock=lambda: NOW,
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(PermissionError, match="regular file"):
        client.status()
    client.close()


def test_open_account_link_checks_active_then_uses_existing_proof_pair_route(
    tmp_path,
) -> None:
    calls: list[tuple[str, str]] = []
    store = OpcClientStateStore(tmp_path / "opc-client.json")

    def handler(request: httpx.Request) -> httpx.Response:
        action = "pair" if request.url.path.endswith("pairings") else "status"
        _request_id(request, action=action)
        calls.append((request.url.path, action))
        installation_id = store.load().installation_id
        if action == "status":
            return httpx.Response(
                200,
                json={"installation_id": installation_id, "status": "active"},
            )
        return httpx.Response(
            201,
            json={
                "installation_id": installation_id,
                "pairing_id": "management-pairing",
                "verification_uri": f"{ORIGIN}/account/opc/management-pairing",
                "expires_at": NOW + 600,
                "status": "active",
            },
        )

    client = OpcClient(
        store,
        origin=ORIGIN,
        label="Linux",
        clock=lambda: NOW,
        transport=httpx.MockTransport(handler),
    )

    link = client.open_account_link()

    assert link["status"] == "active"
    assert link["installation_id"] == client.state.installation_id
    assert calls == [
        ("/v1/opc/status", "status"),
        ("/v1/opc/pairings", "pair"),
    ]
    client.close()


@pytest.mark.parametrize("status", ["pending", "consent_required", "revoked"])
def test_open_account_link_refuses_non_active_status_without_pair_request(
    tmp_path, status: str
) -> None:
    calls: list[str] = []
    store = OpcClientStateStore(tmp_path / "opc-client.json")

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        installation_id = store.load().installation_id
        return httpx.Response(
            200,
            json={"installation_id": installation_id, "status": status},
        )

    client = OpcClient(
        store,
        origin=ORIGIN,
        label="Linux",
        clock=lambda: NOW,
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(OpcClientError, match="active OPC installation"):
        client.open_account_link()
    assert calls == ["/v1/opc/status"]
    client.close()


def test_open_account_link_rejects_authority_change_after_active_status(tmp_path) -> None:
    calls: list[str] = []
    store = OpcClientStateStore(tmp_path / "opc-client.json")

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        installation_id = store.load().installation_id
        if request.url.path.endswith("/status"):
            return httpx.Response(
                200,
                json={"installation_id": installation_id, "status": "active"},
            )
        return httpx.Response(
            201,
            json={
                "installation_id": installation_id,
                "pairing_id": "stale-pairing",
                "verification_uri": f"{ORIGIN}/account/opc/stale-pairing",
                "expires_at": NOW + 600,
                "status": "pending",
            },
        )

    client = OpcClient(
        store,
        origin=ORIGIN,
        label="Linux",
        clock=lambda: NOW,
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(OpcClientError, match="authority changed"):
        client.open_account_link()
    assert calls == ["/v1/opc/status", "/v1/opc/pairings"]
    client.close()


def test_account_cli_default_opens_but_prints_only_sanitized_guidance(
    tmp_path, monkeypatch, capsys
) -> None:
    secret_url = "https://agentonomy.example/account/opc/cli-management-secret"
    calls: list[str] = []

    class FakeClient:
        def __init__(self, _store: object, **kwargs: object) -> None:
            calls.append(str(kwargs))

        def __enter__(self):
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def open_account_link(self) -> dict[str, object]:
            return {
                "installation_id": "opc_" + "a" * 40,
                "pairing_id": "pairing-secret",
                "verification_uri": secret_url,
                "expires_at": NOW + 600,
                "status": "active",
            }

    opened: list[str] = []
    monkeypatch.setattr(opc_cli, "OpcClient", FakeClient)
    monkeypatch.setattr(opc_cli, "open_wallet_browser", lambda uri: opened.append(uri) or True)
    monkeypatch.setattr(opc_cli, "_state_path", lambda _namespace: tmp_path / "client.json")

    namespace = SimpleNamespace(state=None, json=False, no_open=False)
    assert opc_cli._account(namespace) == 0

    output = capsys.readouterr().out
    assert opened == [secret_url]
    assert "active" in output
    assert "browser" in output.lower()
    assert "expiry" in output.lower()
    assert secret_url not in output
    assert "pairing-secret" not in output
    assert "opc_" + "a" * 40 not in output
    assert calls == ["{'allow_loopback_http': False}"]


def test_account_cli_json_never_opens_or_exposes_link_and_no_open_is_explicit(
    tmp_path, monkeypatch, capsys
) -> None:
    secret_url = "https://agentonomy.example/account/opc/json-management-secret"

    class FakeClient:
        def __init__(self, _store: object, **_kwargs: object) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def open_account_link(self) -> dict[str, object]:
            return {
                "installation_id": "opc_" + "b" * 40,
                "pairing_id": "json-pairing-secret",
                "verification_uri": secret_url,
                "expires_at": NOW + 600,
                "status": "active",
            }

    monkeypatch.setattr(opc_cli, "OpcClient", FakeClient)
    monkeypatch.setattr(
        opc_cli,
        "open_wallet_browser",
        lambda _uri: pytest.fail("JSON account output must not open a browser"),
    )
    monkeypatch.setattr(opc_cli, "_state_path", lambda _namespace: tmp_path / "client.json")

    namespace = SimpleNamespace(state=None, json=True, no_open=True)
    assert opc_cli._account(namespace) == 0

    output = capsys.readouterr().out
    result = json.loads(output)
    assert result["status"] == "active"
    assert result["browser_opened"] is False
    assert result["expiry"] == NOW + 600
    assert set(result) == {"status", "browser_opened", "expiry", "instructions"}
    assert secret_url not in output
    assert "json-pairing-secret" not in output
    assert "opc_" + "b" * 40 not in output


def test_account_cli_headless_only_mode_is_the_sensitive_local_fallback(
    tmp_path, monkeypatch, capsys
) -> None:
    secret_url = "https://agentonomy.example/account/opc/headless-management-secret"

    class FakeClient:
        def __init__(self, _store: object, **_kwargs: object) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def open_account_link(self) -> dict[str, object]:
            return {
                "verification_uri": secret_url,
                "expires_at": NOW + 600,
                "status": "active",
            }

    monkeypatch.setattr(opc_cli, "OpcClient", FakeClient)
    monkeypatch.setattr(opc_cli, "_state_path", lambda _namespace: tmp_path / "client.json")

    namespace = SimpleNamespace(state=None, json=False, no_open=True)
    assert opc_cli._account(namespace) == 0

    output = capsys.readouterr().out
    assert secret_url in output
    assert "local" in output.lower()
    assert "do not" in output.lower()


def test_account_cli_parser_supports_sanitized_json_and_explicit_headless_flags() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    opc_cli.configure_opc_parser(commands)

    namespace = parser.parse_args(
        ["opc", "account", "--state", "/tmp/existing-client.json", "--json", "--no-open"]
    )

    assert namespace.opc_command == "account"
    assert str(namespace.state) == "/tmp/existing-client.json"
    assert namespace.json is True
    assert namespace.no_open is True
    assert namespace.handler is opc_cli._account


def test_account_cli_browser_failure_does_not_print_sensitive_link(
    tmp_path, monkeypatch, capsys
) -> None:
    secret_url = "https://agentonomy.example/account/opc/browser-failure-secret"

    class FakeClient:
        def __init__(self, _store: object, **_kwargs: object) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def open_account_link(self) -> dict[str, object]:
            return {
                "verification_uri": secret_url,
                "expires_at": NOW + 600,
                "status": "active",
            }

    monkeypatch.setattr(opc_cli, "OpcClient", FakeClient)
    monkeypatch.setattr(opc_cli, "open_wallet_browser", lambda _uri: False)
    monkeypatch.setattr(opc_cli, "_state_path", lambda _namespace: tmp_path / "client.json")

    assert opc_cli._account(SimpleNamespace(state=None, json=False, no_open=False)) == 0

    output = capsys.readouterr().out
    assert "browser opened: false" in output.lower()
    assert "opc account --no-open" in output
    assert secret_url not in output
