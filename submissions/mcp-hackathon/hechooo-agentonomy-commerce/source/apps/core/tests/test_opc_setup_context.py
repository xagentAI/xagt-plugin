import json
import subprocess
from decimal import Decimal
from html.parser import HTMLParser
from urllib.parse import urlsplit

from eth_account import Account
from eth_account.messages import encode_defunct

from services.account_service.app import CSRF_COOKIE, SESSION_COOKIE, create_app
from services.account_service.console import ACCOUNT_CONSOLE_JS
from services.account_service.opc_service import OpcPairingRow
from shared.hosted_facilitator_protocol import DeviceSigningKey
from shared.opc_protocol import sign_opc_proof
from test_opc_account import ASGIClient, INTERNAL_TOKEN, NOW, ORIGIN, SPENDER, TOKEN, _context, _pair, _public_session
from test_opc_browser_context import authenticate, client_for


class BodyAttributes(HTMLParser):
    def __init__(self, page):
        super().__init__()
        self.attributes = {}
        self.feed(page)

    def handle_starttag(self, tag, attrs):
        if tag == "body":
            self.attributes = dict(attrs)


def _assert_browser_accepts_real_plan(plan, form, identity, target, grant=None):
    """Cross the HTTP/JS contract using production validators, not copied rules."""
    functions = []
    for name in (
        "usdcAtomic", "canonicalAddress", "opcSetupAmountSame",
        "opcSetupNonNegativeAtomic", "opcSetupAllowanceMatchesGrant",
        "opcSetupProductVenues", "opcSetupExpectedScopes",
        "opcSetupGrantImmutableTermsMatch", "opcSetupPlanMatchesReview",
    ):
        start = ACCOUNT_CONSOLE_JS.index(f"  const {name} =")
        end = ACCOUNT_CONSOLE_JS.index("\n  };", start) + len("\n  };")
        functions.append(ACCOUNT_CONSOLE_JS[start:end])
    context = json.dumps({
        "plan": plan, "form": form, "identity": identity,
        "target": target, "grant": grant,
    })
    script = (
        f"const ctx = {context};\n"
        'const CONTROLLED_AGENT_ID = "hermes";\n'
        "const accountState = {wallet_identities: [ctx.identity]};\n"
        "const selectedWalletAddress = ctx.identity.wallet_address.toLowerCase();\n"
        + "\n".join(functions)
        + "\nif (!opcSetupPlanMatchesReview(ctx.plan, ctx.form, ctx.grant, ctx.target)) "
          "throw new Error('Browser rejected real Core plan: ' + ctx.plan.action);\n"
        + "if (!opcSetupAllowanceMatchesGrant(ctx.plan, ctx.form, ctx.grant)) "
          "throw new Error('Browser rejected real Core allowance: ' + ctx.plan.action);\n"
        + "ctx.plan.terms.max_amount_usdc = '999999';\n"
          "if (opcSetupPlanMatchesReview(ctx.plan, ctx.form, ctx.grant, ctx.target)) "
          "throw new Error('Browser accepted authority above reviewed total');\n"
    )
    result = subprocess.run(
        ["node", "-"], input=script, capture_output=True, text=True, timeout=10
    )
    assert result.returncode == 0, result.stderr


def test_opc_bootstrap_is_session_bound_before_wallet_login(tmp_path):
    clock, repository, account, opc = _context(tmp_path)
    first = _pair(opc, DeviceSigningKey.generate())
    second = _pair(opc, DeviceSigningKey.generate())
    for pairing, foreign in ((first, second), (second, first)):
        client = client_for(account, opc, clock)
        assert client.post(urlsplit(pairing["verification_uri"]).path).status_code == 303
        page = client.request("GET", "/account", params={"pairing_id": foreign["pairing_id"]})
        assert page.status_code == 200
        attrs = BodyAttributes(page.text).attributes
        assert attrs.get("data-account-view") == "authorization"
        setup = json.loads(attrs["data-opc-setup"])
        assert set(setup) == {"pairing", "network_configs", "approval_targets", "defaults"}
        assert setup["defaults"] == {"total_usdc": "20", "hourly_usdc": "5", "duration_days": 7}
        assert set(setup["pairing"]) == {
            "pairing_id", "installation_id", "label", "public_jwk_thumbprint",
            "scope", "agent_id", "status", "expires_at",
        }
        assert setup["pairing"]["pairing_id"] == pairing["pairing_id"]
        assert setup["pairing"]["installation_id"] == pairing["installation_id"]
        assert setup["pairing"]["status"] == "pending"
        assert foreign["installation_id"] not in page.text
        assert pairing["verification_uri"] not in page.text
        assert "no-store" in page.headers["cache-control"]
        assert client.request("GET", "/account", headers={"Accept": "application/json"}).status_code == 401
        assert client.request("GET", "/account/opc/pairing").status_code == 401


def test_bootstrap_label_is_data_not_markup(tmp_path):
    clock, _repository, account, opc = _context(tmp_path)
    label = '\"><img src=x onerror="alert(1)"> & laptop'
    pairing = opc.create_pairing(sign_opc_proof(
        DeviceSigningKey.generate(), origin=ORIGIN, action="pair", request_id="hostile-label",
        now=int(NOW.timestamp()), label=label,
    ))
    client = client_for(account, opc, clock)
    client.post(urlsplit(pairing["verification_uri"]).path)
    page = client.request("GET", "/account")
    assert label not in page.text
    assert json.loads(BodyAttributes(page.text).attributes["data-opc-setup"])["pairing"]["label"] == label


def test_ordinary_embedded_view_does_not_become_opc_from_query(tmp_path):
    clock, repository, account, opc = _context(tmp_path)
    pairing = _pair(opc, DeviceSigningKey.generate())
    _public_session(repository, user_id="ordinary", suffix="ordinary")
    client = client_for(account, opc, clock)
    client.cookies.set(SESSION_COOKIE, "browser-ordinary")
    client.cookies.set(CSRF_COOKIE, "csrf-ordinary")
    page = client.request("GET", "/account", params={"view": "authorization", "pairing_id": pairing["pairing_id"]})
    attrs = BodyAttributes(page.text).attributes
    assert attrs["data-account-view"] == "authorization"
    assert "data-opc-setup" not in attrs
    assert "data-account-view" not in BodyAttributes(client.request("GET", "/account").text).attributes


def test_ambiguous_opc_bootstrap_fails_closed(tmp_path):
    clock, repository, account, opc = _context(tmp_path)
    first, second = (_pair(opc, DeviceSigningKey.generate()) for _ in range(2))
    client = client_for(account, opc, clock)
    client.post(urlsplit(first["verification_uri"]).path)
    with repository._write_session() as session:
        session.get(OpcPairingRow, second["pairing_id"]).public_account_session_id = session.get(OpcPairingRow, first["pairing_id"]).public_account_session_id
    result = client.request("GET", "/account")
    assert result.status_code == 409
    assert second["installation_id"] not in result.text


def test_new_setup_uses_real_core_plan_and_one_combined_grant_device_signature(tmp_path):
    clock, repository, account, opc = _context(tmp_path)
    token_address = account.asset_registry.token_address("eip155:137")
    observed = 0
    def rpc(network, method, params):
        assert network == "eip155:137"
        if method == "eth_chainId":
            return "0x89"
        assert method == "eth_call" and params[0]["data"].startswith("0xdd62ed3e")
        assert params[0]["to"].lower() == token_address.lower()
        return hex(observed)
    account._rpc = rpc
    client = ASGIClient(create_app(
        service=account, opc_service=opc, clock=clock, internal_token=INTERNAL_TOKEN,
        audit_summary_reader=lambda *_: [],
        approval_targets={"eip155:137": {"token_address": token_address, "spender_address": SPENDER}},
    ))
    key, wallet = DeviceSigningKey.generate(), Account.create()
    pairing = _pair(opc, key)
    assert client.post(urlsplit(pairing["verification_uri"]).path).status_code == 303
    page = client.request("GET", "/account")
    bootstrap = json.loads(BodyAttributes(page.text).attributes["data-opc-setup"])
    assert bootstrap["approval_targets"]["eip155:137"] == {"token_address": token_address.lower(), "spender_address": SPENDER}
    assert "rpc_url" not in bootstrap["network_configs"]["eip155:137"]
    authenticate(client, wallet)
    headers = {"X-CSRF-Token": client.cookies.get(CSRF_COOKIE)}
    state = client.request("GET", "/account", headers={"Accept": "application/json"}).json()
    identity = state["wallet_identities"][0]
    payload = {"wallet_identity_id": identity["wallet_identity_id"], "network": "eip155:137",
               **bootstrap["defaults"]}
    response = client.post("/account/authorization-plan", headers=headers, json=payload)
    assert response.status_code == 200, response.text
    plan = response.json()
    assert plan["action"] == "sign"
    assert plan["allowance"]["target_atomic"] == "20000000"
    assert plan["allowance"]["status"] == "insufficient"
    browser_form = {"network": "eip155:137", "total": "20.0", "hourly": "5.000000", "duration": 7}
    target = bootstrap["approval_targets"]["eip155:137"]
    _assert_browser_accepts_real_plan(plan, browser_form, identity, target)
    request = {**plan["terms"], "opc_pairing_id": pairing["pairing_id"]}
    challenge_response = client.post("/account/grants", headers=headers, json=request)
    assert challenge_response.status_code == 200, challenge_response.text
    challenge = challenge_response.json()
    assert "OPC Installation ID:" in challenge["message_to_sign"]
    signature = Account.sign_message(encode_defunct(text=challenge["message_to_sign"]), wallet.key).signature.hex()
    approved = client.post("/account/grants", headers=headers, json={**request,
        "challenge_session_id": challenge["session_id"], "signed_message": challenge["message_to_sign"], "signature": signature})
    assert approved.status_code == 201, approved.text
    saved = approved.json()
    assert saved["product_scopes"] == ["marketplace"]
    assert saved["network_scopes"] == ["eip155:137"]
    assert Decimal(saved["max_amount_usdc"]) == 20
    assert Decimal(saved["per_transaction_limit_usdc"]) == 5
    assert client.request("GET", "/account/opc/pairing").json()["pairing"]["status"] == "active"
    token = opc.issue_token(sign_opc_proof(key, origin=ORIGIN, action="token", request_id="setup-token", now=int(clock.value.timestamp())))
    principal = opc.authenticate_access_token(token["access_token"])
    assert principal["wallet_identity_id"] == identity["wallet_identity_id"]
    assert principal["spending_grant_id"] == saved["spending_grant_id"]
    # Only the RPC boundary is simulated. A later observed finite approval
    # changes readiness; no test sends a real chain transaction or payment.
    observed = 20_000_000
    next_plan = client.post("/account/authorization-plan", headers=headers, json={
        **payload, "duration_days": None, "spending_grant_id": saved["spending_grant_id"],
    }).json()
    assert next_plan["action"] == "none"
    assert next_plan["allowance"]["status"] == "sufficient"
    assert next_plan["terms"]["amends_spending_grant_id"] == saved["spending_grant_id"]
    projection = client.request("GET", "/account", headers={"Accept": "application/json"}).json()["current_spending_mandate"]
    _assert_browser_accepts_real_plan(next_plan, {**browser_form, "duration": None}, identity, target, projection)
    amended_plan_response = client.post("/account/authorization-plan", headers=headers, json={
        **payload, "total_usdc": "30.0", "hourly_usdc": "4.000000",
        "duration_days": None, "spending_grant_id": saved["spending_grant_id"],
    })
    assert amended_plan_response.status_code == 200, amended_plan_response.text
    _assert_browser_accepts_real_plan(amended_plan_response.json(), {
        "network": "eip155:137", "total": "30", "hourly": "4", "duration": None,
    }, identity, target, projection)
    assert len(repository.spending_grants(identity["user_id"])) == 1
