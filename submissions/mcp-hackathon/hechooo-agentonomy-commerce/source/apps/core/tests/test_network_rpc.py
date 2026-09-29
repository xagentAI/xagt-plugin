from __future__ import annotations

import json
import traceback
from urllib.error import HTTPError, URLError

import pytest

import services.account_service.app as account_app
from services.account_service.service import AccountService
from services.funding_service.service import FundingService
from shared.config import AppConfig


POLYGON = "eip155:137"
BASE = "eip155:8453"


class FakeResponse:
    def __init__(
        self,
        payload: dict | None = None,
        *,
        raw: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.raw = raw if raw is not None else json.dumps(payload).encode()
        self.headers = {
            "Content-Type": "application/json",
            "Content-Length": str(len(self.raw)),
            **(headers or {}),
        }
        self.read_amounts: list[int | None] = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self, amount: int | None = None) -> bytes:
        self.read_amounts.append(amount)
        return self.raw if amount is None else self.raw[:amount]


def test_network_rpc_transport_routes_by_canonical_network_and_redacts_urls():
    from shared.evm_rpc import NetworkRpcTransport

    calls = []

    def opener(request, timeout):
        request_payload = json.loads(request.data)
        calls.append(
            (
                request.full_url,
                request_payload,
                dict(request.header_items()),
                timeout,
            )
        )
        return FakeResponse(
            {"jsonrpc": "2.0", "id": request_payload["id"], "result": "0x89"}
        )

    transport = NetworkRpcTransport(
        {
            POLYGON: "https://polygon-rpc.example/v1/polygon-secret",
            BASE: "https://base-rpc.example/v1/base-secret",
        },
        opener=opener,
    )

    assert transport(POLYGON, "eth_chainId", []) == "0x89"
    assert calls[0][0].endswith("/v1/polygon-secret")
    assert calls[0][1]["method"] == "eth_chainId"
    assert calls[0][2] == {
        "Accept": "application/json",
        "Content-type": "application/json",
        "User-agent": "Agentonomy-Clink-Node/1.0",
    }
    assert calls[0][3] == 20.0
    with pytest.raises(ValueError, match="unsupported canonical EVM network"):
        transport("eip155:1", "eth_chainId", [])

    transport.opener = lambda *_args, **_kwargs: (_ for _ in ()).throw(
        URLError("request failed for https://polygon-rpc.example/v1/polygon-secret")
    )
    with pytest.raises(RuntimeError) as error:
        transport(POLYGON, "eth_blockNumber", [])
    assert "polygon-secret" not in str(error.value)
    rendered_traceback = "".join(
        traceback.format_exception(error.type, error.value, error.tb)
    )
    assert "polygon-secret" not in rendered_traceback


@pytest.mark.parametrize(
    ("message", "reason_code", "error_code"),
    [
        (
            "insufficient funds for gas * price + value",
            "insufficient_funds",
            -32000,
        ),
        ("insufficient funds", "insufficient_funds", -32003),
        ("intrinsic gas too low", "intrinsic_gas_too_low", -32000),
        ("invalid sender", "invalid_sender", -32000),
        (
            "transaction type not supported",
            "transaction_type_not_supported",
            -32000,
        ),
    ],
)
def test_send_raw_transaction_exposes_only_whitelisted_definite_rejection(
    message, reason_code, error_code
):
    from shared.evm_rpc import NetworkRpcTransport, RpcSubmissionRejected

    def opener(request, timeout):
        assert timeout == 20.0
        request_payload = json.loads(request.data)
        return FakeResponse(
            {
                "jsonrpc": "2.0",
                "id": request_payload["id"],
                "error": {"code": error_code, "message": message},
            }
        )

    transport = NetworkRpcTransport(
        {POLYGON: "https://polygon-rpc.example/private-provider-key"},
        opener=opener,
    )
    signed_raw = "0xdeadbeef"

    with pytest.raises(RpcSubmissionRejected) as error:
        transport(POLYGON, "eth_sendRawTransaction", [signed_raw])

    assert error.value.reason_code == reason_code
    assert str(error.value) == "EVM transaction submission was definitely rejected"
    rendered = "".join(traceback.format_exception(error.type, error.value, error.tb))
    assert message not in rendered
    assert "private-provider-key" not in rendered
    assert "deadbeef" not in rendered


@pytest.mark.parametrize(
    "message",
    [
        "already known",
        "nonce too low",
        "replacement transaction underpriced",
        "fee too low to replace pending transaction",
    ],
)
def test_send_raw_transaction_conflicts_remain_ambiguous_and_redacted(message):
    from shared.evm_rpc import NetworkRpcTransport, RpcSubmissionRejected

    def opener(request, timeout):
        assert timeout == 20.0
        request_payload = json.loads(request.data)
        return FakeResponse(
            {
                "jsonrpc": "2.0",
                "id": request_payload["id"],
                "error": {"code": -32000, "message": message},
            }
        )

    transport = NetworkRpcTransport(
        {POLYGON: "https://polygon-rpc.example/private-provider-key"},
        opener=opener,
    )
    signed_raw = "0xdeadbeef"

    with pytest.raises(RuntimeError) as error:
        transport(POLYGON, "eth_sendRawTransaction", [signed_raw])

    assert not isinstance(error.value, RpcSubmissionRejected)
    assert str(error.value) == "EVM RPC returned an ambiguous error for eip155:137"
    rendered = "".join(traceback.format_exception(error.type, error.value, error.tb))
    assert message not in rendered
    assert "private-provider-key" not in rendered
    assert "deadbeef" not in rendered


@pytest.mark.parametrize(
    "mutate_response",
    [
        lambda response: {**response, "jsonrpc": "1.0"},
        lambda response: {**response, "id": "mismatched-request-id"},
        lambda response: {
            **response,
            "error": {"code": True, "message": "insufficient funds for gas"},
        },
        lambda response: {
            **response,
            "error": {"code": "-32000", "message": "insufficient funds for gas"},
        },
        lambda response: {
            **response,
            "error": {"code": -32603, "message": "insufficient funds for gas"},
        },
        lambda response: {
            **response,
            "error": {"code": -32000, "message": "insufficient funds" + "x" * 300},
        },
    ],
)
def test_send_raw_transaction_malformed_rpc_error_is_ambiguous(mutate_response):
    from shared.evm_rpc import NetworkRpcTransport, RpcSubmissionRejected

    def opener(request, timeout):
        assert timeout == 20.0
        request_payload = json.loads(request.data)
        response = {
            "jsonrpc": "2.0",
            "id": request_payload["id"],
            "error": {"code": -32000, "message": "insufficient funds for gas"},
        }
        return FakeResponse(mutate_response(response))

    transport = NetworkRpcTransport(
        {POLYGON: "https://polygon-rpc.example/private-provider-key"},
        opener=opener,
    )

    with pytest.raises(RuntimeError) as error:
        transport(POLYGON, "eth_sendRawTransaction", ["0xdeadbeef"])

    assert not isinstance(error.value, RpcSubmissionRejected)
    assert "insufficient funds" not in str(error.value)
    assert "private-provider-key" not in str(error.value)
    assert "deadbeef" not in str(error.value)


def test_non_submission_rpc_error_never_becomes_a_definite_rejection():
    from shared.evm_rpc import NetworkRpcTransport, RpcSubmissionRejected

    def opener(request, timeout):
        assert timeout == 20.0
        request_payload = json.loads(request.data)
        return FakeResponse(
            {
                "jsonrpc": "2.0",
                "id": request_payload["id"],
                "error": {
                    "code": -32000,
                    "message": "insufficient funds for gas",
                },
            }
        )

    transport = NetworkRpcTransport(
        {POLYGON: "https://polygon-rpc.example/private-provider-key"},
        opener=opener,
    )

    with pytest.raises(RuntimeError) as error:
        transport(POLYGON, "eth_call", [])

    assert not isinstance(error.value, RpcSubmissionRejected)


def test_http_submission_failure_is_ambiguous_and_redacted():
    from shared.evm_rpc import NetworkRpcTransport, RpcSubmissionRejected

    secret_url = "https://polygon-rpc.example/private-provider-key"

    def opener(_request, timeout):
        assert timeout == 20.0
        raise HTTPError(secret_url, 500, "insufficient funds", {}, None)

    transport = NetworkRpcTransport({POLYGON: secret_url}, opener=opener)
    signed_raw = "0xdeadbeef"

    with pytest.raises(RuntimeError) as error:
        transport(POLYGON, "eth_sendRawTransaction", [signed_raw])

    assert not isinstance(error.value, RpcSubmissionRejected)
    rendered = "".join(traceback.format_exception(error.type, error.value, error.tb))
    assert "private-provider-key" not in rendered
    assert "insufficient funds" not in rendered
    assert "deadbeef" not in rendered


@pytest.mark.parametrize(
    "headers",
    [
        {"Content-Type": "text/plain"},
        {"Content-Type": "application/problem+json"},
        {"Content-Type": ""},
        {"Content-Length": str(65_537)},
        {"Content-Length": "not-an-integer"},
    ],
)
def test_rpc_response_headers_fail_closed_before_error_classification(headers):
    from shared.evm_rpc import NetworkRpcTransport, RpcSubmissionRejected

    def opener(request, timeout):
        assert timeout == 20.0
        request_payload = json.loads(request.data)
        return FakeResponse(
            {
                "jsonrpc": "2.0",
                "id": request_payload["id"],
                "error": {
                    "code": -32000,
                    "message": "insufficient funds for gas",
                },
            },
            headers=headers,
        )

    transport = NetworkRpcTransport(
        {POLYGON: "https://polygon-rpc.example/private-provider-key"},
        opener=opener,
    )

    with pytest.raises(RuntimeError) as error:
        transport(POLYGON, "eth_sendRawTransaction", ["raw-transaction-marker"])

    assert not isinstance(error.value, RpcSubmissionRejected)
    assert str(error.value) == "EVM RPC returned an invalid response for eip155:137"
    assert "private-provider-key" not in repr(error.value)
    assert "insufficient funds" not in repr(error.value)
    assert "raw-transaction-marker" not in repr(error.value)


def test_rpc_response_actual_body_over_64k_is_rejected_without_leaking_body():
    from shared.evm_rpc import NetworkRpcTransport, RpcSubmissionRejected

    marker = "private-response-marker"
    oversized = json.dumps(
        {"jsonrpc": "2.0", "id": "ignored", "padding": marker + "x" * 65_536}
    ).encode()

    response = FakeResponse(raw=oversized, headers={"Content-Length": "64"})

    def opener(_request, timeout):
        assert timeout == 20.0
        return response

    transport = NetworkRpcTransport(
        {POLYGON: "https://polygon-rpc.example/private-provider-key"},
        opener=opener,
    )

    with pytest.raises(RuntimeError) as error:
        transport(POLYGON, "eth_sendRawTransaction", ["raw-transaction-marker"])

    assert not isinstance(error.value, RpcSubmissionRejected)
    assert str(error.value) == "EVM RPC returned an invalid response for eip155:137"
    assert marker not in repr(error.value)
    assert response.read_amounts == [65_537]


def test_rpc_response_duplicate_json_keys_are_rejected():
    from shared.evm_rpc import NetworkRpcTransport, RpcSubmissionRejected

    def opener(request, timeout):
        assert timeout == 20.0
        request_id = json.loads(request.data)["id"]
        raw = (
            '{"jsonrpc":"2.0","id":"'
            + request_id
            + '","result":"0x1","result":"0x2"}'
        ).encode()
        return FakeResponse(raw=raw)

    transport = NetworkRpcTransport(
        {POLYGON: "https://polygon-rpc.example/private-provider-key"},
        opener=opener,
    )

    with pytest.raises(RuntimeError) as error:
        transport(POLYGON, "eth_chainId", [])

    assert not isinstance(error.value, RpcSubmissionRejected)
    assert str(error.value) == "EVM RPC returned an invalid response for eip155:137"


def test_production_account_app_constructs_network_aware_rpc_service(
    tmp_path, monkeypatch
):
    from shared.evm_rpc import NetworkRpcTransport

    monkeypatch.setenv(
        "CLINK_FUNDING_DATABASE_URL",
        f"sqlite+pysqlite:///{tmp_path / 'account.sqlite3'}",
    )
    monkeypatch.setenv("CLINK_POLYGON_RPC_URL", "https://polygon-rpc.example/v1/key")
    monkeypatch.setenv("CLINK_BASE_RPC_URL", "https://base-rpc.example/v1/key")
    captured = {}
    real_service = AccountService

    def construct(*args, **kwargs):
        captured.update(kwargs)
        return real_service(*args, **kwargs)

    monkeypatch.setattr(account_app, "AccountService", construct)

    account_app.create_app(internal_token="token", approval_targets={})

    assert isinstance(captured["rpc_transport"], NetworkRpcTransport)


def test_funding_rpc_validates_chain_before_network_scoped_read(tmp_path):
    calls = []

    def rpc(network, method, _params):
        calls.append((network, method))
        if method == "eth_chainId":
            return "0x2105"
        if method == "eth_blockNumber":
            return "0x20"
        raise AssertionError(method)

    service = FundingService(
        config=AppConfig(
            funding_database_url=f"sqlite+pysqlite:///{tmp_path / 'funding.sqlite3'}"
        ),
        storage_file=tmp_path / "legacy.jsonl",
        rpc_transport=rpc,
    )

    assert service._rpc_call(BASE, "eth_blockNumber", []) == "0x20"
    assert calls == [(BASE, "eth_chainId"), (BASE, "eth_blockNumber")]


def test_funding_rpc_rejects_mismatched_chain_before_requested_read(tmp_path):
    calls = []

    def rpc(network, method, _params):
        calls.append((network, method))
        return "0x89"

    service = FundingService(
        config=AppConfig(
            funding_database_url=f"sqlite+pysqlite:///{tmp_path / 'funding.sqlite3'}"
        ),
        storage_file=tmp_path / "legacy.jsonl",
        rpc_transport=rpc,
    )

    with pytest.raises(RuntimeError, match="RPC chain id does not match"):
        service._rpc_call(BASE, "eth_blockNumber", [])
    assert calls == [(BASE, "eth_chainId")]
