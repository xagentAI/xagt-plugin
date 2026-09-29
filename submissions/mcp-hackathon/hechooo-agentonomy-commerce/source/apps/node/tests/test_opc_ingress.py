from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from clink_node.agent_access import (
    AgentAccessUnauthorizedError,
    CompositeRuntimeAuthenticator,
    RuntimePrincipal,
)
from clink_node.agent_access_http import _public_token, attach_opc_routes
from clink_node.opc_core_client import OpcCoreClient, OpcCoreError


ORIGIN = "https://node.example"
ACCOUNT_ORIGIN = "https://account.example"


def test_opc_core_client_rewrites_public_urls_and_keeps_internal_bearer_private():
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert request.headers["authorization"] == "Bearer core-secret"
        assert request.url.host == "core.internal"
        assert json.loads(request.content) == {"proof": "signed-proof"}
        if request.url.path.endswith("/pairings"):
            return httpx.Response(
                201,
                json={
                    "installation_id": "opc_" + "a" * 40,
                    "pairing_id": "opc_pair_" + "b" * 40,
                    "verification_uri": (
                        "https://core.internal/account/public-token"
                    ),
                    "expires_at": 1_788_451_800,
                    "status": "pending",
                },
            )
        if request.url.path.endswith("/token"):
            return httpx.Response(
                200,
                json={
                    "installation_id": "opc_" + "a" * 40,
                    "access_token": "agentonomy_opc_v1_secret",
                    "token_type": "Bearer",
                    "expires_at": 1_788_451_500,
                    "mcp_url": "http://127.0.0.1:9170/mcp",
                },
            )
        raise AssertionError(request.url.path)

    client = OpcCoreClient(
        account_url="https://core.internal",
        internal_token="core-secret",
        public_origin=ORIGIN,
        account_public_origin=ACCOUNT_ORIGIN,
        transport=httpx.MockTransport(handler),
    )
    try:
        pairing = client.create_pairing("signed-proof")
        token = client.issue_token("signed-proof")
    finally:
        client.close()

    assert pairing == {
        "installation_id": "opc_" + "a" * 40,
        "pairing_id": "opc_pair_" + "b" * 40,
        "verification_uri": f"{ACCOUNT_ORIGIN}/account/public-token",
        "expires_at": 1_788_451_800,
        "status": "pending",
    }
    assert token == {
        "installation_id": "opc_" + "a" * 40,
        "access_token": "agentonomy_opc_v1_secret",
        "token_type": "Bearer",
        "expires_at": 1_788_451_500,
        "mcp_url": f"{ORIGIN}/mcp",
    }
    assert "core-secret" not in json.dumps(pairing | token)
    assert len(calls) == 2


def test_opc_core_client_maps_downstream_failure_without_leaking_detail():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            503,
            json={"detail": "http://core.internal/password=secret"},
        )

    client = OpcCoreClient(
        account_url="https://core.internal",
        internal_token="core-secret",
        public_origin=ORIGIN,
        transport=httpx.MockTransport(handler),
    )
    try:
        with pytest.raises(OpcCoreError) as caught:
            client.create_pairing("signed-proof")
    finally:
        client.close()
    assert caught.value.status_code == 503
    assert str(caught.value) == "OPC Core service unavailable"
    assert "core.internal" not in str(caught.value)
    assert "secret" not in str(caught.value)


def test_opc_core_client_sanitizes_non_http_transport_failures():
    def handler(_request: httpx.Request) -> httpx.Response:
        raise RuntimeError("private core bearer and URL leaked")

    client = OpcCoreClient(
        account_url="https://core.internal",
        internal_token="core-secret",
        public_origin=ORIGIN,
        transport=httpx.MockTransport(handler),
    )
    try:
        with pytest.raises(OpcCoreError) as caught:
            client.create_pairing("signed-proof")
    finally:
        client.close()
    assert caught.value.status_code == 503
    assert str(caught.value) == "OPC Core service unavailable"
    assert "private core" not in str(caught.value)


def test_opc_core_client_authenticate_returns_installation_scoped_principal():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/internal/opc/authenticate"
        assert json.loads(request.content) == {
            "access_token": "agentonomy_opc_v1_secret"
        }
        return httpx.Response(
            200,
            json={
                "issuer": "opc",
                "installation_id": "opc_" + "a" * 40,
                "user_id": "user-1",
                "wallet_identity_id": "wallet-1",
                "agent_id": "hermes",
                "spending_grant_id": "grant-1",
                "scope": "payments",
                "credential_id": "opc_credential_" + "b" * 40,
                "expires_at": 1_788_451_500,
            },
        )

    client = OpcCoreClient(
        account_url="https://core.internal",
        internal_token="core-secret",
        public_origin=ORIGIN,
        transport=httpx.MockTransport(handler),
    )
    try:
        principal = client.authenticate("agentonomy_opc_v1_secret")
    finally:
        client.close()
    assert principal.issuer == "opc"
    assert principal.user_id == "user-1"
    assert principal.agent_id == "hermes"
    assert principal.runtime_id == principal.opc_installation_id
    assert principal.opc_installation_id == "opc_" + "a" * 40


@pytest.mark.parametrize("token", ["agentonomy_opc_v1_", "agentonomy_opc_v1_\n"])
def test_opc_core_client_rejects_an_empty_or_invalid_token_suffix(token):
    client = OpcCoreClient(
        account_url="https://core.internal",
        internal_token="core-secret",
        public_origin=ORIGIN,
        transport=httpx.MockTransport(
            lambda _request: (_ for _ in ()).throw(
                AssertionError("invalid token must not reach Core")
            )
        ),
    )
    try:
        with pytest.raises(AgentAccessUnauthorizedError):
            client.authenticate(token)
    finally:
        client.close()


def test_public_token_rejects_prefix_without_a_suffix():
    with pytest.raises(OpcCoreError):
        _public_token(
            {
                "installation_id": "opc_" + "a" * 40,
                "access_token": "agentonomy_opc_v1_",
                "token_type": "Bearer",
                "expires_at": 1_788_451_500,
                "mcp_url": "https://core.internal/mcp",
            },
            ORIGIN,
        )


def test_opc_core_authentication_outage_fails_closed_as_unavailable():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"detail": "private core trace"})

    client = OpcCoreClient(
        account_url="https://core.internal",
        internal_token="core-secret",
        public_origin=ORIGIN,
        transport=httpx.MockTransport(handler),
    )
    try:
        with pytest.raises(RuntimeError, match="unavailable") as caught:
            client.authenticate("agentonomy_opc_v1_secret")
    finally:
        client.close()
    assert "private core trace" not in str(caught.value)


def test_opc_ingress_exposes_only_proof_routes_and_forwards_no_control_bearer():
    class FakeCore:
        def create_pairing(self, proof: str) -> dict:
            return {
                "installation_id": "opc_" + "a" * 40,
                "pairing_id": "opc_pair_" + "b" * 40,
                "verification_uri": f"{ACCOUNT_ORIGIN}/account/token",
                "expires_at": 1_788_451_800,
                "status": "pending",
            }

        def issue_token(self, proof: str) -> dict:
            return {
                "installation_id": "opc_" + "a" * 40,
                "access_token": "agentonomy_opc_v1_secret",
                "token_type": "Bearer",
                "expires_at": 1_788_451_500,
                "mcp_url": f"{ORIGIN}/mcp",
            }

        def status(self, proof: str) -> dict:
            return {"installation_id": "opc_" + "a" * 40, "status": "active"}

        def revoke(self, proof: str) -> dict:
            return {"installation_id": "opc_" + "a" * 40, "status": "revoked"}

    app = FastAPI()
    attach_opc_routes(
        app,
        FakeCore(),
        public_origin=ORIGIN,
        account_public_origin=ACCOUNT_ORIGIN,
        control_token="control-only-for-c" * 2,
    )

    async def scenario() -> None:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url=ORIGIN,
        ) as client:
            response = await client.post(
                "/v1/opc/pairings",
                json={"proof": "signed-proof"},
            )
            assert response.status_code == 201, response.text
            assert "control-only-for-c" not in response.text
            assert response.json()["verification_uri"].startswith(
                ACCOUNT_ORIGIN + "/account/"
            )

            response = await client.post(
                "/v1/opc/token",
                json={"proof": "signed-proof"},
                headers={"Authorization": "Bearer control-only-for-ccontrol-only-for-c"},
            )
            assert response.status_code == 200
            assert response.json()["mcp_url"] == f"{ORIGIN}/mcp"

            assert (
                await client.get("/v1/opc/token")
            ).status_code == 404
            assert (
                await client.post(
                    "/v1/opc/unknown",
                    json={"proof": "signed-proof"},
                )
            ).status_code == 404
            assert (
                await client.post(
                    "/v1/opc/token",
                    json={"proof": "signed-proof", "user_id": "forged"},
                )
            ).status_code == 422

    asyncio.run(scenario())


def test_runtime_authenticator_routes_disjoint_prefixes_without_fallback():
    calls: list[str] = []

    class C:
        def authenticate(self, token: str) -> RuntimePrincipal:
            calls.append("c:" + token)
            if token == "clink_rt_v1_bad":
                raise AgentAccessUnauthorizedError()
            return RuntimePrincipal(
                user_id="user-c",
                agent_id="agent-c",
                runtime_id="runtime-c",
                credential_id="credential-c",
                issuer="wallet-service",
                scope="payments",
                expires_at=1_788_451_500,
            )

    class O:
        def authenticate(self, token: str) -> RuntimePrincipal:
            calls.append("o:" + token)
            if token == "agentonomy_opc_v1_unavailable":
                raise RuntimeError("OPC Core is unavailable")
            return RuntimePrincipal(
                user_id="user-o",
                agent_id="hermes",
                runtime_id="runtime-o",
                credential_id="credential-o",
                issuer="opc",
                scope="payments",
                expires_at=1_788_451_500,
                opc_installation_id="opc_" + "a" * 40,
            )

    authenticator = CompositeRuntimeAuthenticator(C(), O())
    assert authenticator.authenticate("clink_rt_v1_good").user_id == "user-c"
    principal = authenticator.authenticate("agentonomy_opc_v1_good")
    assert principal.user_id == "user-o"
    assert principal.opc_installation_id == "opc_" + "a" * 40
    with pytest.raises(AgentAccessUnauthorizedError):
        authenticator.authenticate("clink_rt_v1_bad")
    with pytest.raises(RuntimeError, match="unavailable"):
        authenticator.authenticate("agentonomy_opc_v1_unavailable")
    with pytest.raises(AgentAccessUnauthorizedError):
        authenticator.authenticate("unknown-token")
    assert calls == [
        "c:clink_rt_v1_good",
        "o:agentonomy_opc_v1_good",
        "c:clink_rt_v1_bad",
        "o:agentonomy_opc_v1_unavailable",
    ]
