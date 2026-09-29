from datetime import timedelta
from decimal import Decimal

import pytest
from eth_account import Account
from eth_account.messages import encode_defunct

from test_account_console import (
    BASE, POLYGON, SPENDER, TOKEN, allowance, context, create_account_link,
    create_authenticated_session, create_session, grant, identity, internal_headers,
)


def setup_owner(context, *, with_grant=False):
    client, service, repository, _clock = context
    owner = identity("user_1", "a")
    repository.save_wallet_identity(owner)
    current = grant(owner, "embedded").model_copy(update={
        "product_scopes": ["marketplace"], "venue_scopes": ["clink_marketplace"],
        "network_scopes": [POLYGON], "max_amount_usdc": Decimal("100"),
        "hourly_limit_usdc": Decimal("10"), "daily_limit_usdc": Decimal("100"),
    })
    if with_grant:
        repository.save_spending_grant(current)
    create_authenticated_session(client)
    return client, service, repository, owner, current


def form(owner, current=None):
    return {
        "wallet_identity_id": owner.wallet_identity_id, "network": POLYGON,
        "total_usdc": "100", "hourly_usdc": "10",
        "duration_days": None if current else 7,
        "spending_grant_id": current.spending_grant_id if current else None,
    }


def chain_reader(observed):
    def rpc(network, method, params):
        assert network == POLYGON
        if method == "eth_chainId":
            return hex(137)
        assert method == "eth_call"
        assert params[0]["to"].lower() == TOKEN
        assert params[0]["data"].startswith("0xdd62ed3e")
        return hex(observed)
    return rpc


def test_marketplace_projection_keeps_legacy_readiness_separate_from_amount_plan(context):
    client, service, repository, owner, current = setup_owner(context, with_grant=True)
    tiny = allowance(owner, "tiny").model_copy(update={"observed_allowance_atomic": 1})
    repository.save_asset_allowance(tiny)
    state = client.get("/account", headers={"Accept": "application/json"}).json()
    assert state["current_spending_mandate"]["spending_grant_id"] == current.spending_grant_id
    # Existing account bool remains "positive allowance", not full cap coverage.
    assert state["readiness"]["chain_allowances"][POLYGON] is True
    assert state["readiness"]["chain_allowances"][BASE] is False
    service._rpc = chain_reader(1)
    plan = client.post("/account/authorization-plan", json=form(owner, current)).json()
    assert plan["allowance"]["status"] == "insufficient"
    repository.save_asset_allowance(tiny.model_copy(update={"observed_allowance_atomic": 5_000_000}))
    state = client.get("/internal/account-readiness?user_id=user_1", headers=internal_headers()).json()
    assert state["ready"] is True
    assert state["active_spending_mandate"]["product_scopes"] == ["marketplace"]


def test_plan_observes_old_allowance_and_returns_core_terms_without_signing(context):
    client, service, repository, owner, _current = setup_owner(context)
    service._rpc = chain_reader(2**256 - 1)
    response = client.post("/account/authorization-plan", json=form(owner))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["action"] == "sign"
    assert body["terms"]["product_scopes"] == ["marketplace"]
    assert Decimal(body["terms"]["per_transaction_limit_usdc"]) == 10
    assert body["allowance"]["status"] == "sufficient"
    assert body["allowance"]["exceeds_budget"] is True
    assert body["allowance"]["observed_atomic"] == str(2**256 - 1)
    assert body["allowance"]["spender_address"] == SPENDER
    assert repository.spending_grants(owner.user_id) == []
    assert repository.asset_allowances(owner.wallet_identity_id)[0].allowance_tx_hash is None


def test_plan_reuses_consumed_allowance_and_same_grant(context):
    client, service, repository, owner, current = setup_owner(context, with_grant=True)
    repository.save_spending_grant(current.model_copy(update={
        "used_amount_usdc": Decimal("40"), "reserved_amount_usdc": Decimal("5"),
    }))
    service._rpc = chain_reader(60_000_000)
    response = client.post("/account/authorization-plan", json=form(owner, current))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["action"] == "none"
    assert body["allowance"]["target_atomic"] == "60000000"
    assert body["allowance"]["status"] == "sufficient"
    assert body["terms"]["amends_spending_grant_id"] == current.spending_grant_id
    saved = repository.spending_grant(current.spending_grant_id)
    assert saved.used_amount_usdc == 40 and saved.reserved_amount_usdc == 5


def test_plan_rpc_error_is_unknown_not_zero(context):
    client, service, _repository, owner, _current = setup_owner(context)
    def unavailable(*args):
        raise OSError("private upstream detail")
    service._rpc = unavailable
    response = client.post("/account/authorization-plan", json=form(owner))
    assert response.status_code == 200, response.text
    assert response.json()["allowance"]["status"] == "unknown"
    assert response.json()["allowance"]["observed_atomic"] is None
    assert "private upstream" not in response.text


def test_plan_rejects_identity_forgery_csrf_and_implicit_budget_reset(context):
    client, service, repository, owner, current = setup_owner(context, with_grant=True)
    service._rpc = lambda *_args: pytest.fail("must reject before RPC")
    assert client.post("/account/authorization-plan", json=form(owner, current), add_csrf=False).status_code == 403
    forged = {**form(owner, current), "wallet_identity_id": "wallet_identity_other"}
    assert client.post("/account/authorization-plan", json=forged).status_code == 404
    # Omitting the current grant must not produce a second budget.
    assert client.post("/account/authorization-plan", json=form(owner)).status_code == 409
    another = current.model_copy(update={"spending_grant_id": "spending_grant_ambiguous"})
    repository.save_spending_grant(another)
    assert client.post("/account/authorization-plan", json=form(owner, current)).status_code == 409


def test_plan_requires_wallet_authenticated_session(context):
    client, _service, _repository, _clock = context
    create_session(client)
    assert client.post("/account/authorization-plan", json=form(identity("user_1", "a"))).status_code == 401


def test_embedded_view_survives_link_exchange_without_arbitrary_redirect(context):
    client, _service, _repository, _clock = context
    token = create_account_link(client)
    result = client.post(f"/account/{token}?view=authorization&return_to=https://evil.example")
    assert result.status_code == 303
    assert result.headers["location"] == "/account?view=authorization"
    page = client.get(result.headers["location"])
    assert 'data-account-view="authorization"' in page.text
    assert "frame-ancestors 'none'" in page.headers["content-security-policy"]


def test_inspect_preserves_verified_proof(context):
    _client, service, repository, owner, _current = setup_owner(context)
    proof = allowance(owner, "proof")
    repository.save_asset_allowance(proof)
    service._rpc = chain_reader(60_000_000)
    refreshed = service.inspect_asset_allowance(owner.wallet_identity_id, POLYGON, TOKEN, SPENDER)
    assert refreshed.asset_allowance_id == proof.asset_allowance_id
    assert refreshed.allowance_tx_hash == proof.allowance_tx_hash
    assert refreshed.approved_amount_atomic == proof.approved_amount_atomic
    assert refreshed.observed_allowance_atomic == 60_000_000


def test_inspect_wrong_chain_cannot_register_allowance(context):
    _client, service, repository, owner, _current = setup_owner(context)
    service._rpc = lambda *_args: hex(1)
    with pytest.raises(ValueError):
        service.inspect_asset_allowance(owner.wallet_identity_id, POLYGON, TOKEN, SPENDER)
    assert repository.asset_allowances(owner.wallet_identity_id) == []


def test_marketplace_only_mandate_cannot_authorize_prediction(context):
    from services.account_service.schemas import AuthorizationResolutionRequest
    _client, service, repository, owner, current = setup_owner(context, with_grant=True)
    repository.save_asset_allowance(allowance(owner, "scope"))
    common = dict(user_id=owner.user_id, agent_id="hermes", network=POLYGON,
        token_address=TOKEN, spender_address=SPENDER, amount_usdc=Decimal("1"),
        destination="0x" + "55" * 20, resource="https://merchant.example/api")
    before = repository.spending_grant(current.spending_grant_id)
    denied = service.resolve_authorization(AuthorizationResolutionRequest(
        **common, product="prediction_markets", venue="polymarket",
    ))
    assert denied.ready is False
    assert denied.reason_code == "PRODUCT_SCOPE_MISMATCH"
    after = repository.spending_grant(current.spending_grant_id)
    assert after.used_amount_usdc == before.used_amount_usdc
    assert after.reserved_amount_usdc == before.reserved_amount_usdc


def test_future_pending_grant_cannot_be_omitted_to_create_new_budget(context):
    client, service, repository, owner, current = setup_owner(context)
    repository.save_spending_grant(current.model_copy(update={
        "status": "pending", "starts_at": current.starts_at + timedelta(days=1),
    }))
    service._rpc = lambda *_args: pytest.fail("pending grant must block before RPC")
    response = client.post("/account/authorization-plan", json=form(owner))
    assert response.status_code == 409


def test_plan_does_not_switch_to_another_wallet_of_same_user(context):
    client, service, repository, _owner, _current = setup_owner(context)
    # One active wallet per user is enforced by the repository. A historical
    # identity still belongs to this user but cannot replace the signed session.
    other = identity("user_1", "b", status="revoked")
    repository.save_wallet_identity(other)
    service._rpc = lambda *_args: pytest.fail("must retain authenticated wallet")
    assert client.post("/account/authorization-plan", json=form(other)).status_code == 404


def test_failed_refresh_does_not_reuse_previously_positive_observation(context):
    client, service, repository, owner, _current = setup_owner(context)
    previous = allowance(owner, "cached")
    repository.save_asset_allowance(previous)
    def unavailable(*args):
        raise OSError("upstream unavailable")
    service._rpc = unavailable
    response = client.post("/account/authorization-plan", json=form(owner))
    assert response.status_code == 200
    assert response.json()["allowance"]["status"] == "unknown"
    assert response.json()["allowance"]["observed_atomic"] is None
    stale = repository.asset_allowance(previous.asset_allowance_id)
    assert stale.status == "stale"
    assert stale.observed_allowance_atomic == previous.observed_allowance_atomic
    assert stale.allowance_tx_hash == previous.allowance_tx_hash


def test_planned_terms_use_real_challenge_and_amend_same_budget(context):
    client, service, repository, owner, _current = setup_owner(context)
    service._rpc = chain_reader(100_000_000)
    # Fixed synthetic fixture wallet, never a real user key or network call.
    wallet = Account.from_key(bytes.fromhex("a" * 64))

    def sign_terms(terms):
        challenge_response = client.post("/account/grants", json=terms)
        assert challenge_response.status_code == 200, challenge_response.text
        challenge = challenge_response.json()
        signature = Account.sign_message(
            encode_defunct(text=challenge["message_to_sign"]), wallet.key,
        ).signature.hex()
        created = client.post("/account/grants", json={
            **terms, "challenge_session_id": challenge["session_id"],
            "signed_message": challenge["message_to_sign"], "signature": signature,
        })
        assert created.status_code == 201, created.text
        return repository.spending_grant(created.json()["spending_grant_id"])

    plan = client.post("/account/authorization-plan", json=form(owner)).json()
    current = sign_terms(plan["terms"])
    assert current.product_scopes == ["marketplace"]
    assert current.venue_scopes == ["clink_marketplace"]
    assert current.max_amount_usdc == 100
    repository.save_spending_grant(current.model_copy(update={
        "used_amount_usdc": Decimal("40"), "reserved_amount_usdc": Decimal("5"),
    }))
    changed = {**form(owner, current), "total_usdc": "120"}
    amended_plan = client.post("/account/authorization-plan", json=changed).json()
    amended = sign_terms(amended_plan["terms"])
    assert amended.spending_grant_id == current.spending_grant_id
    assert amended.max_amount_usdc == 120
    assert amended.used_amount_usdc == 40
    assert amended.reserved_amount_usdc == 5
    assert amended.daily_limit_usdc == current.daily_limit_usdc
    assert amended.per_transaction_limit_usdc == current.per_transaction_limit_usdc
    assert amended.expires_at == current.expires_at
