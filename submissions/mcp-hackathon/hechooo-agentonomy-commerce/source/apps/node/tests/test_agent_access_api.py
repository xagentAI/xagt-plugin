import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from apps.node.clink_node.agent_access import AgentAccessService
from apps.node.clink_node.api import NodeApiContext, create_app
from apps.node.clink_node.config import AgentAccessSettings, NodeSettings, Profile
from apps.node.clink_node.paths import NodePaths
from apps.node.clink_node.storage.agent_access import AgentAccessRepository
from apps.node.clink_node.storage.postgres import PostgresNodeRepository
from apps.node.tests.test_mcp_gateway import NativeCore, NativePrediction, NativeBusiness
from apps.node.tests.test_agent_account_views import ScopedCore


CONTROL = "manager-control-token-not-for-sandboxes"


def fixture(tmp_path):
    repo = PostgresNodeRepository(f"sqlite+pysqlite:///{tmp_path / 'node.sqlite3'}")
    repo.migrate()
    now = [datetime.now(UTC)]
    service = AgentAccessService(AgentAccessRepository(repo.engine), issuer="wallet-app", token_key=b"t" * 32, clock=lambda: now[0])
    settings = replace(NodeSettings.defaults(Profile.SERVER, paths=NodePaths.from_home(tmp_path)),
                       agent_access=AgentAccessSettings(True, "wallet-app", "https://agents.example/mcp"))
    context = NodeApiContext(settings=settings, repository=repo, interaction_service=None,
                             session_token="legacy-session", core=ScopedCore(), marketplace=NativeBusiness("marketplace"),
                             prediction_markets=NativePrediction("prediction-markets"),
                             agent_access_service=service, agent_control_token=CONTROL)
    return context, now


def test_java_registration_credentials_and_restart_reuse_one_identity(tmp_path):
    context, now = fixture(tmp_path)
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(context)), base_url="http://127.0.0.1") as client:
            headers = {"Authorization": "Bearer " + CONTROL}
            payload = {"subject_id": "wallet-user-1", "external_agent_id": "java-agent-1"}
            assert (await client.post("/v1/c/agents", json=payload)).status_code == 401
            registered = await client.post("/v1/c/agents", json=payload, headers=headers)
            assert registered.status_code == 201, registered.text
            binding = registered.json()
            assert (await client.post("/v1/c/agents", json=payload, headers=headers)).json()["agent_id"] == binding["agent_id"]
            path = "/v1/c/agents/" + binding["agent_id"]
            status = await client.get(path + "/runtime", headers=headers)
            assert status.status_code == 200
            assert status.json() == {"agent_id": binding["agent_id"], "runtime": None}
            first = await client.post(path + "/runtime-credentials", headers=headers,
                                      json={"runtime_id": "run1", "request_id": "issue1", "scope": "payments"})
            assert first.status_code == 201, first.text
            credential = first.json()
            assert credential["mcp_url"] == "https://agents.example/mcp"
            assert first.headers["cache-control"] == "no-store"
            assert CONTROL not in first.text
            principal = context.agent_access_service.authenticate(credential["access_token"])
            assert principal.user_id == binding["user_id"]
            status = await client.get(path + "/runtime", headers=headers)
            assert status.headers["cache-control"] == "no-store"
            assert status.json()["runtime"]["credential_id"] == credential["credential_id"]
            assert status.json()["runtime"]["status"] == "active"
            assert "access_token" not in status.text and "digest" not in status.text
            assert (await client.get(path + "/runtime")).status_code == 401
            # A runtime token is not a Java management credential.
            assert (await client.post(path + "/account-links", json={"kind": "core"},
                                     headers={"Authorization": "Bearer " + credential["access_token"]})).status_code == 401
            account = (await client.get(path + "/account", headers=headers)).json()
            assert account["balances"]["agent_spending_authorization"]["remaining_usdc"]["total"] == "23"
            replaced = await client.post(path + "/runtime-credentials", headers=headers, json={
                "runtime_id": "run2", "request_id": "issue2", "replaces_credential_id": credential["credential_id"],
            })
            assert replaced.status_code == 201, replaced.text
            with pytest.raises(ValueError):
                context.agent_access_service.authenticate(credential["access_token"])
            await client.post(path + "/runtimes/run1/revoke", headers=headers)
            new_principal = context.agent_access_service.authenticate(replaced.json()["access_token"])
            assert new_principal.user_id == principal.user_id
            assert new_principal.agent_id == principal.agent_id
            assert new_principal.runtime_id == "run2"
            now[0] += timedelta(minutes=16)
            with pytest.raises(ValueError):
                context.agent_access_service.authenticate(replaced.json()["access_token"])
            status = await client.get(path + "/runtime", headers=headers)
            assert status.json()["runtime"]["credential_id"] == replaced.json()["credential_id"]
            assert status.json()["runtime"]["status"] == "expired"
            assert (await client.get("/v1/c/agents/missing/runtime", headers=headers)).status_code == 404
    asyncio.run(scenario())


def test_c_ingress_blocks_legacy_account_bypass_and_identity_forgery(tmp_path):
    context, _ = fixture(tmp_path)
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(context)), base_url="http://127.0.0.1") as client:
            for path in ("/v1/account/readiness?user_id=another", "/v1/account/summary?user_id=another", "/v1/activity?user_id=another", "/v1/node", "/openapi.json"):
                assert (await client.get(path)).status_code == 404
            response = await client.post("/v1/c/agents", headers={"Authorization": "Bearer " + CONTROL},
                                         json={"subject_id": "alice", "external_agent_id": "agent1", "user_id": "victim"})
            assert response.status_code == 422 and "victim" not in response.text
            assert (await client.post("/v1/c/agents", headers={"Authorization": "Bearer " + CONTROL}, content=b"x" * 65537)).status_code == 413
    asyncio.run(scenario())


def test_enabled_c_mode_cannot_fall_back_to_unauthenticated_app(tmp_path):
    context, _ = fixture(tmp_path)
    with pytest.raises(ValueError):
        create_app(replace(context, agent_access_service=None))


def test_runtime_revoke_blocks_new_issue_but_replays_and_new_runtime_work(tmp_path):
    context, _ = fixture(tmp_path)

    async def scenario():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(context)),
            base_url="http://127.0.0.1",
        ) as client:
            headers = {"Authorization": "Bearer " + CONTROL}
            registered = await client.post(
                "/v1/c/agents",
                json={"subject_id": "alice", "external_agent_id": "agent-a"},
                headers=headers,
            )
            assert registered.status_code == 201
            agent_id = registered.json()["agent_id"]
            path = "/v1/c/agents/" + agent_id
            request = {
                "runtime_id": "runtime-a",
                "request_id": "request-a",
                "scope": "payments",
            }
            first = await client.post(
                path + "/runtime-credentials",
                headers=headers,
                json=request,
            )
            assert first.status_code == 201
            first_body = first.json()
            revoked = await client.post(
                path + "/runtimes/runtime-a/revoke",
                headers=headers,
            )
            assert revoked.status_code == 200
            replay = await client.post(
                path + "/runtime-credentials",
                headers=headers,
                json=request,
            )
            assert replay.status_code == 201
            assert replay.json() == first_body
            delayed = await client.post(
                path + "/runtime-credentials",
                headers=headers,
                json={
                    "runtime_id": "runtime-a",
                    "request_id": "request-a-after-stop",
                    "scope": "payments",
                    "replaces_credential_id": first_body["credential_id"],
                },
            )
            assert delayed.status_code == 409
            before_issue = await client.post(
                path + "/runtimes/runtime-b/revoke",
                headers=headers,
            )
            assert before_issue.status_code == 200
            assert (
                await client.post(
                    path + "/runtime-credentials",
                    headers=headers,
                    json={
                        "runtime_id": "runtime-b",
                        "request_id": "request-b",
                        "scope": "payments",
                        "replaces_credential_id": first_body["credential_id"],
                    },
                )
            ).status_code == 409
            fresh = await client.post(
                path + "/runtime-credentials",
                headers=headers,
                json={
                    "runtime_id": "runtime-c",
                    "request_id": "request-c",
                    "scope": "payments",
                    "replaces_credential_id": first_body["credential_id"],
                },
            )
            assert fresh.status_code == 201, fresh.text
            assert (
                await client.get(path + "/runtime", headers=headers)
            ).json()["runtime"]["status"] == "active"

    asyncio.run(scenario())
