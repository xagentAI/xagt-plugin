from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import anyio
import httpx
import pytest
from eth_account import Account
from eth_account.messages import encode_defunct

from services.account_service.opc_service import OpcAccountService
from services.account_service.app import CSRF_COOKIE, SESSION_COOKIE, create_app
from services.account_service.repository import AccountRepository
from services.account_service.schemas import (
    AssetAllowance,
    PublicAccountSession,
    SpendingGrant,
    SpendingGrantRequest,
    WalletIdentity,
)
from services.account_service.service import AccountService
from shared.hosted_facilitator_protocol import DeviceSigningKey
from shared.opc_protocol import installation_id, sign_opc_proof


NOW = datetime(2026, 9, 4, 2, 0, tzinfo=UTC)
ORIGIN = "https://agentonomy.example"
TOKEN = "0x" + "11" * 20
SPENDER = "0x" + "22" * 20
INTERNAL_TOKEN = "opc-test-internal-token"


class Clock:
    def __init__(self) -> None:
        self.value = NOW

    def __call__(self) -> datetime:
        return self.value


class ASGIClient:
    def __init__(self, app) -> None:
        self.app = app
        self.cookies = httpx.Cookies()

    def request(self, method: str, url: str, **kwargs):
        async def send():
            transport = httpx.ASGITransport(app=self.app, raise_app_exceptions=False)
            async with httpx.AsyncClient(
                transport=transport,
                base_url="https://testserver",
                cookies=self.cookies,
            ) as client:
                response = await client.request(method, url, **kwargs)
                self.cookies.update(response.cookies)
                return response

        return anyio.run(send)

    def post(self, url: str, **kwargs):
        return self.request("POST", url, **kwargs)


def _context(tmp_path):
    clock = Clock()
    repository = AccountRepository(f"sqlite+pysqlite:///{tmp_path / 'opc.db'}")
    account = AccountService(repository, domain="account.agentonomy.test", clock=clock)
    opc = OpcAccountService(
        account,
        origin=ORIGIN,
        token_signing_key=b"o" * 32,
        clock=clock,
    )
    return clock, repository, account, opc


def _pair(opc: OpcAccountService, key: DeviceSigningKey, request_id: str = "pair-1"):
    return opc.create_pairing(
        sign_opc_proof(
            key,
            origin=ORIGIN,
            action="pair",
            request_id=request_id,
            now=int(NOW.timestamp()),
            label="Pilot Linux",
        )
    )


def _identity(repository: AccountRepository, wallet, *, user_id: str) -> WalletIdentity:
    identity = WalletIdentity(
        wallet_identity_id=f"wallet_{user_id}",
        user_id=user_id,
        wallet_address=wallet.address,
        status="active",
        proof_hash="proof",
        verified_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )
    repository.save_wallet_identity(identity)
    return identity


def _grant(repository: AccountRepository, identity: WalletIdentity) -> SpendingGrant:
    grant = SpendingGrant(
        spending_grant_id=f"grant_{identity.user_id}",
        wallet_identity_id=identity.wallet_identity_id,
        user_id=identity.user_id,
        agent_id="hermes",
        status="active",
        max_amount_usdc=Decimal("25"),
        per_transaction_limit_usdc=Decimal("2"),
        hourly_limit_usdc=Decimal("2"),
        daily_limit_usdc=Decimal("5"),
        product_scopes=["marketplace", "prediction_markets"],
        network_scopes=["eip155:137"],
        asset_scopes=[TOKEN],
        starts_at=NOW,
        expires_at=NOW + timedelta(days=30),
        created_at=NOW,
        updated_at=NOW,
    )
    repository.save_spending_grant(grant)
    return grant


def _public_session(
    repository: AccountRepository, *, user_id: str, suffix: str
) -> PublicAccountSession:
    session = PublicAccountSession(
        public_account_session_id=f"public_{suffix}",
        token_digest=hashlib.sha256(f"token-{suffix}".encode()).hexdigest(),
        browser_session_digest=hashlib.sha256(f"browser-{suffix}".encode()).hexdigest(),
        csrf_token_digest=hashlib.sha256(f"csrf-{suffix}".encode()).hexdigest(),
        user_id=user_id,
        expires_at=NOW + timedelta(minutes=15),
        exchanged_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )
    repository.create_public_account_session(session)
    return session


def _attach_existing(
    opc: OpcAccountService,
    repository: AccountRepository,
    key: DeviceSigningKey,
    wallet,
    identity: WalletIdentity,
    grant: SpendingGrant,
) -> dict:
    pairing = _pair(opc, key)
    session = _public_session(
        repository,
        user_id=identity.user_id,
        suffix=f"existing-{identity.user_id}",
    )
    opc.claim_pairing(
        pairing["pairing_id"],
        user_id=identity.user_id,
        public_account_session_id=session.public_account_session_id,
    )
    challenge = opc.create_installation_challenge(
        pairing["pairing_id"],
        user_id=identity.user_id,
        public_account_session_id=session.public_account_session_id,
        spending_grant_id=grant.spending_grant_id,
    )
    signature = Account.sign_message(
        encode_defunct(text=challenge["message_to_sign"]), wallet.key
    ).signature.hex()
    return opc.approve_installation(
        challenge["session_id"],
        challenge["message_to_sign"],
        signature,
    )


def test_pair_attach_token_authenticate_and_revoke_share_the_existing_grant(tmp_path) -> None:
    clock, repository, _account, opc = _context(tmp_path)
    wallet = Account.create("existing-wallet")
    identity = _identity(repository, wallet, user_id="c-user-1")
    grant = _grant(repository, identity)
    key = DeviceSigningKey.generate()
    grant_count = len(repository.spending_grants(identity.user_id))

    installation = _attach_existing(opc, repository, key, wallet, identity, grant)
    assert installation["status"] == "active"
    assert installation["spending_grant_id"] == grant.spending_grant_id
    assert len(repository.spending_grants(identity.user_id)) == grant_count

    token = opc.issue_token(
        sign_opc_proof(
            key,
            origin=ORIGIN,
            action="token",
            request_id="token-1",
            now=int(clock.value.timestamp()),
        )
    )
    principal = opc.authenticate_access_token(token["access_token"])
    assert set(token) == {
        "installation_id",
        "access_token",
        "token_type",
        "expires_at",
        "mcp_url",
    }
    assert principal == {
        "issuer": "opc",
        "installation_id": installation_id(key.public_jwk),
        "user_id": identity.user_id,
        "wallet_identity_id": identity.wallet_identity_id,
        "agent_id": "hermes",
        "spending_grant_id": grant.spending_grant_id,
        "scope": "payments",
        "credential_id": principal["credential_id"],
        "expires_at": token["expires_at"],
    }

    opc.revoke(
        sign_opc_proof(
            key,
            origin=ORIGIN,
            action="revoke",
            request_id="revoke-1",
            now=int(clock.value.timestamp()),
        )
    )
    with pytest.raises(ValueError, match="revoked"):
        opc.authenticate_access_token(token["access_token"])
    with pytest.raises(ValueError, match="revoked"):
        _pair(opc, key, request_id="pair-after-revoke")


def test_active_management_sessions_preserve_authority_and_are_user_scoped(tmp_path) -> None:
    clock, repository, _account, opc = _context(tmp_path)
    users = []
    for suffix in ("a", "b"):
        wallet = Account.create(f"management-{suffix}")
        identity = _identity(repository, wallet, user_id=f"management-{suffix}")
        grant = _grant(repository, identity)
        grant = grant.model_copy(update={
            "used_amount_usdc": Decimal("1"),
            "reserved_amount_usdc": Decimal("0.5"),
        })
        repository.save_spending_grant(grant)
        key = DeviceSigningKey.generate()
        installation = _attach_existing(opc, repository, key, wallet, identity, grant)
        issued = opc.issue_token(sign_opc_proof(
            key, origin=ORIGIN, action="token", request_id=f"token-{suffix}",
            now=int(clock.value.timestamp()),
        ))
        users.append((key, identity, grant, installation, issued))

    opened = []
    for key, identity, grant, installation, issued in users:
        before_installation = opc.installation(installation["installation_id"])
        before_grants = repository.spending_grants(identity.user_id)
        before_principal = opc.authenticate_access_token(issued["access_token"])
        link = _pair(opc, key, request_id="account-management-1")
        assert link["status"] == "active"
        assert _pair(opc, key, request_id="account-management-1") == link
        token = link["verification_uri"].rsplit("/", 1)[1]
        session = repository.public_account_session(hashlib.sha256(token.encode()).hexdigest())
        assert session is not None
        assert session.user_id == identity.user_id
        assert session.authenticated_wallet_identity_id is None
        assert session.authenticated_at is None
        context = opc.browser_pairing(session.public_account_session_id)
        assert context["status"] == "active"
        assert context["wallet_identity_id"] == identity.wallet_identity_id
        assert context["spending_grant_id"] == grant.spending_grant_id
        assert opc.installation(installation["installation_id"]) == before_installation
        assert repository.spending_grants(identity.user_id) == before_grants
        assert opc.authenticate_access_token(issued["access_token"]) == before_principal
        opened.append((link, session))

    assert opened[0][0]["verification_uri"] != opened[1][0]["verification_uri"]
    with pytest.raises(ValueError, match="not available"):
        opc.claim_pairing(
            opened[0][0]["pairing_id"], user_id=users[1][1].user_id,
            public_account_session_id=opened[1][1].public_account_session_id,
        )
    key = users[0][0]
    opc.revoke(sign_opc_proof(
        key, origin=ORIGIN, action="revoke", request_id="management-revoke",
        now=int(clock.value.timestamp()),
    ))
    with pytest.raises(ValueError, match="revoked"):
        _pair(opc, key, request_id="account-management-2")


def test_active_management_browser_session_does_not_authenticate_wallet(tmp_path) -> None:
    clock, repository, account, opc = _context(tmp_path)
    wallet = Account.create("management-http")
    identity = _identity(repository, wallet, user_id="management-http")
    grant = _grant(repository, identity)
    key = DeviceSigningKey.generate()
    _attach_existing(opc, repository, key, wallet, identity, grant)
    link = _pair(opc, key, request_id="management-http-open")
    app = create_app(
        service=account, opc_service=opc, internal_token=INTERNAL_TOKEN,
        clock=clock, session_ttl=timedelta(minutes=15),
        audit_summary_reader=lambda _user_id, _limit: [], approval_targets={},
    )
    client = ASGIClient(app)
    path = "/account/" + link["verification_uri"].rsplit("/", 1)[1]
    assert client.post(path).status_code == 303
    page = client.request("GET", "/account")
    assert page.status_code == 200
    assert "data-opc-setup" in page.text
    assert client.request("GET", "/account", headers={"Accept": "application/json"}).status_code == 401
    assert client.request("GET", "/account/opc/pairing").status_code == 401
    # A copied, already-exchanged link does not authenticate a second browser.
    other = ASGIClient(app)
    assert other.post(path).status_code == 404


def test_pair_and_token_request_replay_return_the_same_result(tmp_path) -> None:
    clock, repository, _account, opc = _context(tmp_path)
    wallet = Account.create("replay-wallet")
    identity = _identity(repository, wallet, user_id="user-replay")
    grant = _grant(repository, identity)
    key = DeviceSigningKey.generate()
    first_pairing = _pair(opc, key)
    assert _pair(opc, key) == first_pairing
    _attach_existing(opc, repository, key, wallet, identity, grant)

    proof = sign_opc_proof(
        key,
        origin=ORIGIN,
        action="token",
        request_id="same-token-request",
        now=int(clock.value.timestamp()),
    )
    first = opc.issue_token(proof)
    second = opc.issue_token(proof)
    assert second == first


def test_old_grant_signature_does_not_activate_a_pending_installation(tmp_path) -> None:
    _clock, repository, account, opc = _context(tmp_path)
    wallet = Account.create("old-signature-wallet")
    pairing_key = DeviceSigningKey.generate()
    pairing = _pair(opc, pairing_key)
    user_id = opc.pairing(pairing["pairing_id"])["target_user_id"]
    identity = _identity(repository, wallet, user_id=user_id)

    request = SpendingGrantRequest(
        user_id=user_id,
        wallet_identity_id=identity.wallet_identity_id,
        agent_id="hermes",
        max_amount_usdc=Decimal("25"),
        per_transaction_limit_usdc=Decimal("2"),
        hourly_limit_usdc=Decimal("2"),
        daily_limit_usdc=Decimal("5"),
        product_scopes=["marketplace", "prediction_markets"],
        network_scopes=["eip155:137"],
        asset_scopes=[TOKEN],
        starts_at=NOW,
        expires_at=NOW + timedelta(days=30),
    )
    challenge = account.create_spending_grant_challenge(request)
    signature = Account.sign_message(
        encode_defunct(text=challenge.message_to_sign), wallet.key
    ).signature.hex()
    account.create_spending_grant(
        request.model_copy(
            update={
                "session_id": challenge.session_id,
                "signed_message": challenge.message_to_sign,
                "signature": signature,
            }
        )
    )

    assert opc.installation(installation_id(pairing_key.public_jwk))["status"] == "pending"
    with pytest.raises(ValueError, match="not active"):
        opc.issue_token(
            sign_opc_proof(
                pairing_key,
                origin=ORIGIN,
                action="token",
                request_id="old-signature-token",
                now=int(NOW.timestamp()),
            )
        )


def test_first_grant_signature_can_atomically_bind_the_pairing(tmp_path) -> None:
    _clock, repository, account, opc = _context(tmp_path)
    wallet = Account.create("first-grant-wallet")
    pairing_key = DeviceSigningKey.generate()
    pairing = _pair(opc, pairing_key)
    pairing_record = opc.pairing(pairing["pairing_id"])
    user_id = pairing_record["target_user_id"]
    identity = _identity(repository, wallet, user_id=user_id)
    request = SpendingGrantRequest(
        user_id=user_id,
        wallet_identity_id=identity.wallet_identity_id,
        agent_id="hermes",
        max_amount_usdc=Decimal("25"),
        per_transaction_limit_usdc=Decimal("2"),
        hourly_limit_usdc=Decimal("2"),
        daily_limit_usdc=Decimal("5"),
        product_scopes=["marketplace", "prediction_markets"],
        network_scopes=["eip155:137"],
        asset_scopes=[TOKEN],
        starts_at=NOW,
        expires_at=NOW + timedelta(days=30),
        opc_installation=opc.grant_installation_clause(
            pairing["pairing_id"],
            user_id=user_id,
            public_account_session_id=pairing_record["public_account_session_id"],
            grant_expires_at=NOW + timedelta(days=30),
        ),
        created_by_public_account_session_id=pairing_record[
            "public_account_session_id"
        ],
    )
    challenge = account.create_spending_grant_challenge(request)
    assert "OPC Installation ID:" in challenge.message_to_sign
    signature = Account.sign_message(
        encode_defunct(text=challenge.message_to_sign), wallet.key
    ).signature.hex()

    grant = account.create_spending_grant(
        request.model_copy(
            update={
                "session_id": challenge.session_id,
                "signed_message": challenge.message_to_sign,
                "signature": signature,
            }
        )
    )

    installed = opc.installation(installation_id(pairing_key.public_jwk))
    assert installed["status"] == "active"
    assert installed["spending_grant_id"] == grant.spending_grant_id


def test_internal_and_browser_routes_preserve_control_and_account_boundaries(tmp_path) -> None:
    clock, repository, account, opc = _context(tmp_path)
    wallet = Account.create("api-wallet")
    identity = _identity(repository, wallet, user_id="api-user")
    grant = _grant(repository, identity)
    device_key = DeviceSigningKey.generate()
    app = create_app(
        service=account,
        opc_service=opc,
        internal_token=INTERNAL_TOKEN,
        clock=clock,
        session_ttl=timedelta(minutes=15),
        audit_summary_reader=lambda _user_id, _limit: [],
        approval_targets={},
    )
    client = ASGIClient(app)
    pair_proof = sign_opc_proof(
        device_key,
        origin=ORIGIN,
        action="pair",
        request_id="api-pair",
        now=int(clock.value.timestamp()),
        label="API Linux",
    )
    assert client.post("/internal/opc/pairings", json={"proof": pair_proof}).status_code == 401
    paired = client.post(
        "/internal/opc/pairings",
        headers={"Authorization": f"Bearer {INTERNAL_TOKEN}"},
        json={"proof": pair_proof},
    )
    assert paired.status_code == 201
    pairing_id = paired.json()["pairing_id"]

    browser_token = "api-browser"
    csrf_token = "api-csrf"
    repository.create_public_account_session(
        PublicAccountSession(
            public_account_session_id="public-api-existing",
            token_digest=hashlib.sha256(b"api-public-token").hexdigest(),
            browser_session_digest=hashlib.sha256(browser_token.encode()).hexdigest(),
            csrf_token_digest=hashlib.sha256(csrf_token.encode()).hexdigest(),
            user_id=identity.user_id,
            expires_at=NOW + timedelta(minutes=15),
            exchanged_at=NOW,
            authenticated_wallet_identity_id=identity.wallet_identity_id,
            authenticated_at=NOW,
            created_at=NOW,
            updated_at=NOW,
        )
    )
    client.cookies.set(SESSION_COOKIE, browser_token)
    client.cookies.set(CSRF_COOKIE, csrf_token)
    csrf_headers = {"X-CSRF-Token": csrf_token}
    assert client.post(
        f"/account/opc/pairings/{pairing_id}/claim",
        headers=csrf_headers,
        json={},
    ).status_code == 200
    challenge_response = client.post(
        f"/account/opc/pairings/{pairing_id}/challenge",
        headers=csrf_headers,
        json={"spending_grant_id": grant.spending_grant_id},
    )
    assert challenge_response.status_code == 200
    challenge = challenge_response.json()
    signature = Account.sign_message(
        encode_defunct(text=challenge["message_to_sign"]), wallet.key
    ).signature.hex()
    approved = client.post(
        "/account/opc/installations/approve",
        headers=csrf_headers,
        json={
            "challenge_session_id": challenge["session_id"],
            "signed_message": challenge["message_to_sign"],
            "signature": signature,
        },
    )
    assert approved.status_code == 200

    token_proof = sign_opc_proof(
        device_key,
        origin=ORIGIN,
        action="token",
        request_id="api-token",
        now=int(clock.value.timestamp()),
    )
    issued = client.post(
        "/internal/opc/token",
        headers={"Authorization": f"Bearer {INTERNAL_TOKEN}"},
        json={"proof": token_proof},
    )
    assert issued.status_code == 200
    authenticated = client.post(
        "/internal/opc/authenticate",
        headers={"Authorization": f"Bearer {INTERNAL_TOKEN}"},
        json={"access_token": issued.json()["access_token"]},
    )
    assert authenticated.status_code == 200
    assert authenticated.json()["user_id"] == identity.user_id


def test_authorization_resolution_uses_the_exact_active_opc_installation(tmp_path) -> None:
    clock = Clock()
    repository = AccountRepository(f"sqlite+pysqlite:///{tmp_path / 'opc-resolution.db'}")
    account = AccountService(
        repository,
        domain="account.agentonomy.test",
        clock=clock,
        network_configs={
            "eip155:137": {
                "chain_id": 137,
                "required_confirmations": 3,
                "token_symbol": "USDC",
                "token_decimals": 6,
                "token_address": TOKEN,
            }
        },
    )
    opc = OpcAccountService(
        account,
        origin=ORIGIN,
        token_signing_key=b"o" * 32,
        clock=clock,
    )
    wallet = Account.create("opc-resolution-wallet")
    identity = _identity(repository, wallet, user_id="opc-resolution-user")
    grant = _grant(repository, identity)
    repository.save_asset_allowance(
        AssetAllowance(
            asset_allowance_id="opc_resolution_allowance",
            wallet_identity_id=identity.wallet_identity_id,
            network="eip155:137",
            token_address=TOKEN,
            token_symbol="USDC",
            token_decimals=6,
            spender_address=SPENDER,
            approved_amount_atomic=25_000_000,
            observed_allowance_atomic=25_000_000,
            status="active",
            confirmed_block=1,
            last_chain_check_at=NOW,
            created_at=NOW,
            updated_at=NOW,
        )
    )
    device_key = DeviceSigningKey.generate()
    installation = _attach_existing(
        opc, repository, device_key, wallet, identity, grant
    )
    app = create_app(
        service=account,
        opc_service=opc,
        internal_token=INTERNAL_TOKEN,
        clock=clock,
        audit_summary_reader=lambda _user_id, _limit: [],
        approval_targets={},
    )
    client = ASGIClient(app)
    payload = {
        "user_id": identity.user_id,
        "agent_id": "hermes",
        "opc_installation_id": installation["installation_id"],
        "product": "marketplace",
        "network": "eip155:137",
        "token_address": TOKEN,
        "spender_address": SPENDER,
        "merchant_trust_tier": "clink_verified",
        "amount_usdc": "1",
        "destination": "0x" + "33" * 20,
        "resource": "opc-resolution-purchase",
    }

    resolved = client.post(
        "/internal/authorization-resolution",
        headers={"Authorization": f"Bearer {INTERNAL_TOKEN}"},
        json=payload,
    )

    assert resolved.status_code == 200
    assert resolved.json()["ready"] is True
    assert resolved.json()["wallet_identity_id"] == identity.wallet_identity_id
    assert resolved.json()["spending_grant_id"] == grant.spending_grant_id
    assert resolved.json()["opc_installation_id"] == installation["installation_id"]

    opc.revoke(
        sign_opc_proof(
            device_key,
            origin=ORIGIN,
            action="revoke",
            request_id="revoke-before-resolution",
            now=int(clock.value.timestamp()),
        )
    )
    revoked = client.post(
        "/internal/authorization-resolution",
        headers={"Authorization": f"Bearer {INTERNAL_TOKEN}"},
        json=payload,
    )
    assert revoked.status_code == 200
    assert revoked.json()["ready"] is False
    assert revoked.json()["reason_code"] == "OPC_INSTALLATION_NOT_READY"
    assert revoked.json()["opc_installation_id"] == installation["installation_id"]


def test_legacy_authorization_resolution_response_does_not_add_opc_field(tmp_path) -> None:
    clock, repository, account, opc = _context(tmp_path)
    app = create_app(
        service=account,
        opc_service=opc,
        internal_token=INTERNAL_TOKEN,
        clock=clock,
        audit_summary_reader=lambda _user_id, _limit: [],
        approval_targets={},
    )
    response = ASGIClient(app).post(
        "/internal/authorization-resolution",
        headers={"Authorization": f"Bearer {INTERNAL_TOKEN}"},
        json={
            "user_id": "legacy-user",
            "agent_id": "hermes",
            "product": "marketplace",
            "network": "eip155:137",
            "token_address": TOKEN,
            "spender_address": SPENDER,
            "amount_usdc": "1",
            "destination": "0x" + "33" * 20,
            "resource": "legacy-purchase",
        },
    )

    assert response.status_code == 200
    assert "opc_installation_id" not in response.json()


def test_browser_opc_routes_require_csrf_wallet_auth_and_pairing_ownership(tmp_path) -> None:
    clock, repository, account, opc = _context(tmp_path)
    first_wallet = Account.create("first-api-wallet")
    second_wallet = Account.create("second-api-wallet")
    first_identity = _identity(repository, first_wallet, user_id="first-api-user")
    _identity(repository, second_wallet, user_id="second-api-user")
    key = DeviceSigningKey.generate()
    pairing = _pair(opc, key, request_id="owned-api-pair")
    app = create_app(
        service=account,
        opc_service=opc,
        internal_token=INTERNAL_TOKEN,
        clock=clock,
        audit_summary_reader=lambda _user_id, _limit: [],
        approval_targets={},
    )
    client = ASGIClient(app)
    browser_token = "first-browser"
    csrf_token = "first-csrf"
    repository.create_public_account_session(
        PublicAccountSession(
            public_account_session_id="public-first-existing",
            token_digest=hashlib.sha256(b"first-public-token").hexdigest(),
            browser_session_digest=hashlib.sha256(browser_token.encode()).hexdigest(),
            csrf_token_digest=hashlib.sha256(csrf_token.encode()).hexdigest(),
            user_id=first_identity.user_id,
            expires_at=NOW + timedelta(minutes=15),
            exchanged_at=NOW,
            authenticated_wallet_identity_id=first_identity.wallet_identity_id,
            authenticated_at=NOW,
            created_at=NOW,
            updated_at=NOW,
        )
    )
    client.cookies.set(SESSION_COOKIE, browser_token)
    client.cookies.set(CSRF_COOKIE, csrf_token)
    path = f"/account/opc/pairings/{pairing['pairing_id']}/claim"
    assert client.post(path, json={}).status_code == 403
    assert client.post(
        path,
        headers={"X-CSRF-Token": csrf_token},
        json={},
    ).status_code == 200
    assert opc.pairing(pairing["pairing_id"])["target_user_id"] == first_identity.user_id


def test_signed_grant_amendment_requires_fresh_device_consent(tmp_path) -> None:
    clock, repository, account, opc = _context(tmp_path)
    wallet = Account.create("amendment-wallet")
    identity = _identity(repository, wallet, user_id="amendment-user")
    grant = _grant(repository, identity)
    key = DeviceSigningKey.generate()
    _attach_existing(opc, repository, key, wallet, identity, grant)
    old_token = opc.issue_token(
        sign_opc_proof(
            key,
            origin=ORIGIN,
            action="token",
            request_id="before-amendment",
            now=int(clock.value.timestamp()),
        )
    )
    request = SpendingGrantRequest(
        user_id=grant.user_id,
        wallet_identity_id=grant.wallet_identity_id,
        agent_id=grant.agent_id,
        max_amount_usdc=Decimal("20"),
        per_transaction_limit_usdc=Decimal("1"),
        hourly_limit_usdc=Decimal("1"),
        daily_limit_usdc=Decimal("4"),
        product_scopes=grant.product_scopes,
        venue_scopes=grant.venue_scopes,
        merchant_scopes=grant.merchant_scopes,
        merchant_trust_scopes=grant.merchant_trust_scopes,
        notification_mode=grant.notification_mode,
        network_scopes=grant.network_scopes,
        asset_scopes=grant.asset_scopes,
        starts_at=grant.starts_at,
        expires_at=grant.expires_at,
        amends_spending_grant_id=grant.spending_grant_id,
    )
    challenge = account.create_spending_grant_challenge(request)
    signature = Account.sign_message(
        encode_defunct(text=challenge.message_to_sign), wallet.key
    ).signature.hex()
    account.create_spending_grant(
        request.model_copy(
            update={
                "session_id": challenge.session_id,
                "signed_message": challenge.message_to_sign,
                "signature": signature,
            }
        )
    )
    assert opc.installation(installation_id(key.public_jwk))["status"] == "consent_required"
    with pytest.raises(ValueError, match="not active"):
        opc.authenticate_access_token(old_token["access_token"])

    pairing = _pair(opc, key, request_id="consent-after-amendment")
    pairing_record = opc.pairing(pairing["pairing_id"])
    fresh_challenge = opc.create_installation_challenge(
        pairing["pairing_id"],
        user_id=identity.user_id,
        public_account_session_id=pairing_record["public_account_session_id"],
        spending_grant_id=grant.spending_grant_id,
    )
    fresh_signature = Account.sign_message(
        encode_defunct(text=fresh_challenge["message_to_sign"]), wallet.key
    ).signature.hex()
    assert opc.approve_installation(
        fresh_challenge["session_id"],
        fresh_challenge["message_to_sign"],
        fresh_signature,
    )["status"] == "active"


def test_unsigned_limit_reduction_does_not_revoke_device_consent(tmp_path) -> None:
    _clock, repository, account, opc = _context(tmp_path)
    wallet = Account.create("reduction-wallet")
    identity = _identity(repository, wallet, user_id="reduction-user")
    grant = _grant(repository, identity)
    key = DeviceSigningKey.generate()
    _attach_existing(opc, repository, key, wallet, identity, grant)

    account.reduce_spending_grant(
        grant.spending_grant_id,
        max_amount_usdc=Decimal("20"),
        per_transaction_limit_usdc=Decimal("1"),
        hourly_limit_usdc=Decimal("1"),
        daily_limit_usdc=Decimal("4"),
    )

    assert opc.installation(installation_id(key.public_jwk))["status"] == "active"


def test_revoked_pairing_rolls_back_first_grant_and_leaves_challenge_reusable(tmp_path) -> None:
    _clock, repository, account, opc = _context(tmp_path)
    wallet = Account.create("atomic-rollback-wallet")
    key = DeviceSigningKey.generate()
    pairing = _pair(opc, key, request_id="atomic-rollback-pair")
    record = opc.pairing(pairing["pairing_id"])
    identity = _identity(repository, wallet, user_id=record["target_user_id"])
    request = SpendingGrantRequest(
        user_id=identity.user_id,
        wallet_identity_id=identity.wallet_identity_id,
        agent_id="hermes",
        max_amount_usdc=Decimal("25"),
        per_transaction_limit_usdc=Decimal("2"),
        hourly_limit_usdc=Decimal("2"),
        daily_limit_usdc=Decimal("5"),
        product_scopes=["marketplace", "prediction_markets"],
        network_scopes=["eip155:137"],
        asset_scopes=[TOKEN],
        starts_at=NOW,
        expires_at=NOW + timedelta(days=30),
        opc_installation=opc.grant_installation_clause(
            pairing["pairing_id"],
            user_id=identity.user_id,
            public_account_session_id=record["public_account_session_id"],
            grant_expires_at=NOW + timedelta(days=30),
        ),
        created_by_public_account_session_id=record["public_account_session_id"],
    )
    challenge = account.create_spending_grant_challenge(request)
    signature = Account.sign_message(
        encode_defunct(text=challenge.message_to_sign), wallet.key
    ).signature.hex()
    opc.revoke(
        sign_opc_proof(
            key,
            origin=ORIGIN,
            action="revoke",
            request_id="revoke-before-grant-commit",
            now=int(NOW.timestamp()),
        )
    )

    with pytest.raises(ValueError, match="revoked"):
        account.create_spending_grant(
            request.model_copy(
                update={
                    "session_id": challenge.session_id,
                    "signed_message": challenge.message_to_sign,
                    "signature": signature,
                }
            )
        )
    grant_id = account.repository.account_session(challenge.session_id).payload[
        "spending_grant_id"
    ]
    assert repository.spending_grant(grant_id) is None
    assert repository.account_session(challenge.session_id).consumed_at is None


def test_access_token_expiry_and_repeated_authentication_are_read_only(tmp_path) -> None:
    clock, repository, _account, opc = _context(tmp_path)
    wallet = Account.create("token-expiry-wallet")
    identity = _identity(repository, wallet, user_id="token-expiry-user")
    grant = _grant(repository, identity)
    key = DeviceSigningKey.generate()
    _attach_existing(opc, repository, key, wallet, identity, grant)
    token = opc.issue_token(
        sign_opc_proof(
            key,
            origin=ORIGIN,
            action="token",
            request_id="expiring-token",
            now=int(clock.value.timestamp()),
        )
    )
    before = len(repository.audit_events(user_id=identity.user_id))
    first = opc.authenticate_access_token(token["access_token"])
    second = opc.authenticate_access_token(token["access_token"])
    assert second == first
    assert len(repository.audit_events(user_id=identity.user_id)) == before

    clock.value += timedelta(seconds=301)
    with pytest.raises(ValueError, match="expired"):
        opc.authenticate_access_token(token["access_token"])


def test_grant_or_wallet_revocation_immediately_invalidates_opc_tokens(tmp_path) -> None:
    clock, repository, account, opc = _context(tmp_path)
    wallet = Account.create("authority-revocation-wallet")
    identity = _identity(repository, wallet, user_id="authority-revocation-user")
    grant = _grant(repository, identity)
    first_key = DeviceSigningKey.generate()
    _attach_existing(opc, repository, first_key, wallet, identity, grant)
    first_token = opc.issue_token(
        sign_opc_proof(
            first_key,
            origin=ORIGIN,
            action="token",
            request_id="before-grant-revocation",
            now=int(clock.value.timestamp()),
        )
    )

    account.revoke_spending_grant(grant.spending_grant_id)
    with pytest.raises(ValueError, match="authority is unavailable"):
        opc.authenticate_access_token(first_token["access_token"])

    second_wallet = Account.create("wallet-revocation-wallet")
    second_identity = _identity(
        repository,
        second_wallet,
        user_id="wallet-revocation-user",
    )
    second_grant = _grant(repository, second_identity)
    second_key = DeviceSigningKey.generate()
    _attach_existing(
        opc,
        repository,
        second_key,
        second_wallet,
        second_identity,
        second_grant,
    )
    second_token = opc.issue_token(
        sign_opc_proof(
            second_key,
            origin=ORIGIN,
            action="token",
            request_id="before-wallet-revocation",
            now=int(clock.value.timestamp()),
        )
    )

    account.revoke_wallet_identity(second_identity.wallet_identity_id)
    with pytest.raises(ValueError, match="authority is unavailable"):
        opc.authenticate_access_token(second_token["access_token"])
