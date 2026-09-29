from __future__ import annotations

import json
from typing import Any

import pytest

from rpc import (
    SUPPORTED_RPC_METHODS,
    JsonRpcTransport,
    PacedRpcTransport,
    RpcConfigurationError,
    RpcProtocolError,
    RpcReadError,
    RpcSubmissionRejected,
    RpcSubmissionUnknown,
    RpcTransportError,
    require_distinct_rpc_origins,
)


TX_HASH = "0x" + "aa" * 32
RAW_TRANSACTION = "0x" + "bb" * 80


class FakeResponse:
    def __init__(
        self,
        payload: object | None = None,
        *,
        status_code: int = 200,
        raw: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self.content = raw if raw is not None else json.dumps(payload).encode("utf-8")
        self.headers = {
            "content-type": "application/json",
            "content-length": str(len(self.content)),
            **(headers or {}),
        }


class FakeClient:
    def __init__(self, response: FakeResponse | Exception) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    def post(self, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append({"url": url, **kwargs})
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def response_for(request_id: object, *, result: object = "0x1") -> FakeResponse:
    return FakeResponse({"jsonrpc": "2.0", "id": request_id, "result": result})


def transport(
    client: FakeClient,
    *,
    url: str = "https://rpc.example.invalid/private-provider-token",
    environment: str = "production",
) -> JsonRpcTransport:
    return JsonRpcTransport(
        url,
        environment=environment,
        client=client,
        timeout_seconds=3.5,
    )


class RecordingClock:
    def __init__(self) -> None:
        self.current = 100.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.current

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.current += seconds


def test_paced_transport_delays_only_calls_after_the_first_and_delegates_close() -> None:
    class Delegate:
        def __init__(self) -> None:
            self.calls: list[tuple[str, list[Any], str | int | None]] = []
            self.closed = False

        def call(
            self,
            method: str,
            params: list[Any],
            *,
            request_id: str | int | None = None,
        ) -> str:
            self.calls.append((method, params, request_id))
            return method

        def close(self) -> None:
            self.closed = True

    clock = RecordingClock()
    delegate = Delegate()
    rpc = PacedRpcTransport(
        delegate,
        min_interval_seconds=0.25,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )

    assert rpc.call("eth_chainId", [], request_id="one") == "eth_chainId"
    clock.current += 0.05
    assert rpc.call("eth_call", ["0x"], request_id="two") == "eth_call"
    clock.current += 0.30
    assert rpc.call("eth_getCode", ["0x"], request_id="three") == "eth_getCode"

    assert clock.sleeps == [pytest.approx(0.20)]
    assert delegate.calls == [
        ("eth_chainId", [], "one"),
        ("eth_call", ["0x"], "two"),
        ("eth_getCode", ["0x"], "three"),
    ]
    rpc.close()
    assert delegate.closed is True


@pytest.mark.parametrize("value", [-0.01, True, 60.01, "0.25"])
def test_paced_transport_rejects_invalid_intervals(value: object) -> None:
    with pytest.raises(RpcConfigurationError, match="interval"):
        PacedRpcTransport(object(), min_interval_seconds=value)  # type: ignore[arg-type]


def test_only_hosted_methods_are_accepted_and_request_is_strict_json_rpc() -> None:
    client = FakeClient(response_for("request-1", result="0x2105"))
    rpc = transport(client)

    assert rpc.call("eth_chainId", [], request_id="request-1") == "0x2105"
    assert set(client.calls[0]) == {"url", "json", "headers", "timeout"}
    assert client.calls[0]["json"] == {
        "jsonrpc": "2.0",
        "id": "request-1",
        "method": "eth_chainId",
        "params": [],
    }
    assert client.calls[0]["timeout"] == 3.5
    assert client.calls[0]["headers"] == {
        "accept": "application/json",
        "content-type": "application/json",
    }
    assert SUPPORTED_RPC_METHODS == frozenset(
        {
            "eth_chainId",
            "eth_getTransactionCount",
            "eth_estimateGas",
            "eth_maxPriorityFeePerGas",
            "eth_gasPrice",
            "eth_sendRawTransaction",
            "eth_getTransactionByHash",
            "eth_getTransactionReceipt",
            "eth_getBlockByNumber",
            "eth_call",
            "eth_getCode",
        }
    )

    for method in ("eth_call", "eth_getCode"):
        client.response = response_for("request-2", result="0x")
        assert rpc.call(method, [], request_id="request-2") == "0x"

    with pytest.raises(RpcProtocolError, match="method"):
        rpc.call("debug_traceTransaction", [], request_id="request-3")
    assert len(client.calls) == 3


@pytest.mark.parametrize(
    "url",
    [
        "http://rpc.example.invalid/provider-token",
        "https://user:password@rpc.example.invalid/provider-token",
        "https://rpc.example.invalid/provider-token#fragment",
        "https://rpc.example.invalid/provider\n-token",
        "https://rpc.example.invalid/provider\x00-token",
    ],
)
def test_production_url_is_https_and_secrets_never_enter_repr_or_configuration_error(
    url: str,
) -> None:
    with pytest.raises(RpcConfigurationError) as caught:
        JsonRpcTransport(url, environment="production", client=FakeClient(response_for("x")))

    assert "password" not in repr(caught.value)
    assert "api_key" not in repr(caught.value)
    assert "secret" not in repr(caught.value)
    assert "provider-token" not in repr(caught.value)


def test_production_query_api_key_is_allowed_but_never_rendered() -> None:
    client = FakeClient(TimeoutError("https://rpc.example.invalid/provider?api_key=secret"))
    rpc = JsonRpcTransport(
        "https://rpc.example.invalid/provider-token?api_key=secret",
        environment="production",
        client=client,
    )

    assert "api_key" not in repr(rpc)
    assert "secret" not in repr(rpc)
    with pytest.raises(RpcTransportError) as caught:
        rpc.call("eth_chainId", [], request_id="query-secret")
    assert "api_key" not in str(caught.value)
    assert "secret" not in str(caught.value)


@pytest.mark.parametrize(
    "url",
    [
        "http://rpc.example.invalid/provider-token",
        "http://127.0.0.1:80/provider-token",
        "https://rpc.example.invalid:443/provider-token",
    ],
)
def test_test_environment_rejects_remote_http_and_explicit_default_ports(url: str) -> None:
    with pytest.raises(RpcConfigurationError):
        JsonRpcTransport(url, environment="test", client=FakeClient(response_for("x")))


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8545/provider-token",
        "https://rpc.example.invalid/provider-token",
        "https://127.0.0.1/provider-token",
    ],
)
def test_test_environment_allows_remote_https_and_loopback_http(url: str) -> None:
    rpc = JsonRpcTransport(
        url,
        environment="test",
        client=FakeClient(response_for("x")),
    )
    assert "provider-token" not in repr(rpc)


def test_production_requires_distinct_canonical_rpc_origins() -> None:
    with pytest.raises(RpcConfigurationError, match="distinct"):
        require_distinct_rpc_origins(
            "https://rpc-a.example/provider-one",
            "https://rpc-a.example/provider-two",
            environment="production",
        )

    require_distinct_rpc_origins(
        "https://rpc-a.example/provider-one",
        "https://rpc-b.example/provider-two",
        environment="production",
    )


def test_test_environment_requires_distinct_canonical_rpc_origins() -> None:
    with pytest.raises(RpcConfigurationError, match="distinct"):
        require_distinct_rpc_origins(
            "http://127.0.0.1:8545/primary",
            "http://127.0.0.1:8545/watcher",
            environment="test",
        )

    require_distinct_rpc_origins(
        "https://rpc-a.example/provider-one",
        "https://rpc-b.example/provider-two",
        environment="test",
    )


@pytest.mark.parametrize("method", ["eth_sendRawTransaction"])
@pytest.mark.parametrize(
    "failure",
    [TimeoutError("secret-provider-url"), EOFError("raw-secret"), OSError("provider secret")],
)
def test_submission_transport_failures_are_submission_unknown_and_redacted(
    method: str, failure: Exception
) -> None:
    rpc = transport(FakeClient(failure))

    with pytest.raises(RpcSubmissionUnknown) as caught:
        rpc.call(method, [RAW_TRANSACTION], request_id="send-1")

    assert caught.value.reason_code == "submission_unknown"
    assert caught.value.needs_lookup is True
    rendered = repr(caught.value) + str(caught.value)
    assert "secret" not in rendered
    assert RAW_TRANSACTION not in rendered


def test_read_transport_failure_is_fail_closed_but_not_submission_unknown() -> None:
    rpc = transport(FakeClient(TimeoutError("provider secret")))

    with pytest.raises(RpcTransportError) as caught:
        rpc.call("eth_chainId", [], request_id="read-1")

    assert caught.value.reason_code == "rpc_unavailable"
    assert not isinstance(caught.value, RpcSubmissionUnknown)
    assert "secret" not in str(caught.value)


@pytest.mark.parametrize("status_code", [400, 500, 502])
def test_submission_http_failure_is_submission_unknown(status_code: int) -> None:
    rpc = transport(
        FakeClient(
            FakeResponse(
                {"provider": "private-provider", "raw": RAW_TRANSACTION},
                status_code=status_code,
            )
        )
    )

    with pytest.raises(RpcSubmissionUnknown) as caught:
        rpc.call("eth_sendRawTransaction", [RAW_TRANSACTION], request_id="send-http")

    assert caught.value.reason_code == "submission_unknown"
    assert "private-provider" not in str(caught.value)
    assert RAW_TRANSACTION not in str(caught.value)


@pytest.mark.parametrize("raw", [b"not-json", b"{\"jsonrpc\":\"2.0\"}"])
def test_submission_parse_failure_is_submission_unknown(raw: bytes) -> None:
    rpc = transport(FakeClient(FakeResponse(raw=raw)))

    with pytest.raises(RpcSubmissionUnknown):
        rpc.call("eth_sendRawTransaction", [RAW_TRANSACTION], request_id="send-parse")


def test_explicit_already_known_error_is_ambiguous_and_requires_lookup() -> None:
    client = FakeClient(
        FakeResponse(
            {
                "jsonrpc": "2.0",
                "id": "send-known",
                "error": {"code": -32000, "message": "already known"},
            }
        )
    )
    rpc = transport(client)

    with pytest.raises(RpcSubmissionUnknown) as caught:
        rpc.call("eth_sendRawTransaction", [RAW_TRANSACTION], request_id="send-known")

    assert caught.value.reason_code == "submission_unknown"
    assert caught.value.classification == "already_known"
    assert caught.value.needs_lookup is True
    assert "already known" not in str(caught.value)
    assert RAW_TRANSACTION not in repr(caught.value)


@pytest.mark.parametrize(
    ("message", "reason_code"),
    [
        ("insufficient funds", "insufficient_funds"),
        ("intrinsic gas too low", "intrinsic_gas_too_low"),
        ("invalid sender", "invalid_sender"),
        ("transaction type not supported", "transaction_type_not_supported"),
    ],
)
def test_whitelisted_definite_submission_error_is_bounded_and_redacted(
    message: str, reason_code: str
) -> None:
    client = FakeClient(
        FakeResponse(
            {
                "jsonrpc": "2.0",
                "id": "send-rejected",
                "error": {"code": -32000, "message": message},
            }
        )
    )
    rpc = transport(client)

    with pytest.raises(RpcSubmissionRejected) as caught:
        rpc.call("eth_sendRawTransaction", [RAW_TRANSACTION], request_id="send-rejected")

    assert caught.value.reason_code == reason_code
    assert message not in str(caught.value)
    assert RAW_TRANSACTION not in repr(caught.value)


def test_unknown_submission_error_is_conservative_and_provider_message_is_hidden() -> None:
    client = FakeClient(
        FakeResponse(
            {
                "jsonrpc": "2.0",
                "id": "send-error",
                "error": {"code": -32099, "message": "provider-private-message"},
            }
        )
    )
    rpc = transport(client)

    with pytest.raises(RpcSubmissionUnknown) as caught:
        rpc.call("eth_sendRawTransaction", [RAW_TRANSACTION], request_id="send-error")

    assert caught.value.reason_code == "submission_unknown"
    assert caught.value.classification == "provider_error"
    assert "provider-private-message" not in str(caught.value)


def test_read_json_rpc_error_is_fail_closed_without_provider_message() -> None:
    client = FakeClient(
        FakeResponse(
            {
                "jsonrpc": "2.0",
                "id": "read-error",
                "error": {"code": -32000, "message": "provider-private-message"},
            }
        )
    )
    rpc = transport(client)

    with pytest.raises(RpcReadError) as caught:
        rpc.call("eth_chainId", [], request_id="read-error")

    assert caught.value.reason_code == "rpc_error"
    assert "provider-private-message" not in str(caught.value)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda response: {**response, "jsonrpc": "1.0"},
        lambda response: {**response, "id": "wrong-id"},
        lambda response: {**response, "result": "0x1", "error": {"code": -1}},
        lambda response: {**response, "result": "0x1", "error": None},
        lambda response: {"jsonrpc": "2.0", "id": response["id"]},
    ],
)
def test_read_malformed_json_rpc_response_is_protocol_error(mutate) -> None:
    request_id = "read-malformed"
    base = {"jsonrpc": "2.0", "id": request_id, "result": "0x1"}
    rpc = transport(FakeClient(FakeResponse(mutate(base))))

    with pytest.raises(RpcProtocolError):
        rpc.call("eth_chainId", [], request_id=request_id)


def test_json_rpc_response_id_requires_type_and_value_equality() -> None:
    rpc = transport(FakeClient(response_for(True, result="0x1")))

    with pytest.raises(RpcProtocolError):
        rpc.call("eth_chainId", [], request_id=1)


@pytest.mark.parametrize("result", [TX_HASH.upper(), "0x" + "aa" * 31, 1, None])
def test_send_raw_transaction_result_must_be_canonical_tx_hash(result: object) -> None:
    rpc = transport(FakeClient(response_for("send-hash", result=result)))

    with pytest.raises(RpcSubmissionUnknown) as caught:
        rpc.call("eth_sendRawTransaction", [RAW_TRANSACTION], request_id="send-hash")

    assert caught.value.reason_code == "submission_unknown"
    assert caught.value.classification == "invalid_result"


def test_send_raw_transaction_accepts_canonical_lowercase_tx_hash() -> None:
    rpc = transport(FakeClient(response_for("send-hash", result=TX_HASH)))

    assert (
        rpc.call("eth_sendRawTransaction", [RAW_TRANSACTION], request_id="send-hash")
        == TX_HASH
    )


def test_duplicate_response_members_fail_closed_and_oversized_body_is_bounded() -> None:
    request_id = "duplicate"
    duplicate = (
        '{"jsonrpc":"2.0","id":"duplicate","result":"0x1",'
        '"result":"0x2"}'
    ).encode("ascii")
    rpc = transport(FakeClient(FakeResponse(raw=duplicate)))
    with pytest.raises(RpcProtocolError):
        rpc.call("eth_chainId", [], request_id=request_id)

    oversized = b"{" + b"x" * (65_536 + 1) + b"}"
    rpc = transport(FakeClient(FakeResponse(raw=oversized)))
    with pytest.raises(RpcProtocolError) as caught:
        rpc.call("eth_chainId", [], request_id="oversized")
    assert "x" * 100 not in str(caught.value)


def test_rpc_error_repr_never_contains_private_endpoint() -> None:
    client = FakeClient(TimeoutError("https://rpc.example.invalid/path/private-token"))
    rpc = transport(client)

    with pytest.raises(RpcTransportError) as caught:
        rpc.call("eth_getBlockByNumber", ["latest", False], request_id="read-secret")

    assert "private-token" not in repr(rpc)
    assert "private-token" not in repr(caught.value)
