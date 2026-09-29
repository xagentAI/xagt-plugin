from datetime import timedelta
from urllib.parse import urlsplit

import pytest
from eth_account import Account
from eth_account.messages import encode_defunct

from services.account_service.app import CSRF_COOKIE, SESSION_COOKIE, create_app
from services.account_service.opc_service import OpcInstallationRow, OpcPairingRow
from shared.hosted_facilitator_protocol import DeviceSigningKey
from test_opc_account import (
    ASGIClient, INTERNAL_TOKEN, _attach_existing, _context, _grant,
    _identity, _pair, _public_session,
)


def client_for(account, opc, clock):
    return ASGIClient(create_app(
        service=account, opc_service=opc, clock=clock,
        internal_token=INTERNAL_TOKEN, audit_summary_reader=lambda *_: [],
        approval_targets={},
    ))


def get_context(client):
    return client.request("GET", "/account/opc/pairing")


def authenticate(client, wallet=None):
    wallet = wallet or Account.create()
    headers = {"X-CSRF-Token": client.cookies.get(CSRF_COOKIE)}
    response = client.post("/account/wallet-challenge", headers=headers,
                           json={"wallet_address": wallet.address})
    assert response.status_code == 200
    challenge = response.json()
    signature = Account.sign_message(
        encode_defunct(text=challenge["message_to_sign"]), wallet.key
    ).signature.hex()
    verified = client.post("/account/wallet-verify", headers=headers, json={
        "challenge_session_id": challenge["session_id"],
        "signed_message": challenge["message_to_sign"], "signature": signature,
    })
    assert verified.status_code == 200


def exchange(client, pairing):
    response = client.post(urlsplit(pairing["verification_uri"]).path)
    assert response.status_code == 303
    assert get_context(client).status_code == 401
    authenticate(client)


def test_context_requires_session_and_hides_other_sessions(tmp_path):
    clock, repository, account, opc = _context(tmp_path)
    client = client_for(account, opc, clock)
    assert get_context(client).status_code == 401
    first = _pair(opc, DeviceSigningKey.generate())
    second = _pair(opc, DeviceSigningKey.generate())
    exchange(client, first)
    result = get_context(client)
    assert result.status_code == 200
    body = result.json()["pairing"]
    assert body["pairing_id"] == first["pairing_id"]
    assert body["installation_id"] == first["installation_id"]
    assert body["installation_id"] != second["installation_id"]
    assert body["status"] == "pending"
    assert body["agent_id"] == "hermes"
    assert body["scope"] == "payments"
    assert set(body) == {
        "pairing_id", "installation_id", "label", "public_jwk_thumbprint",
        "scope", "agent_id", "status", "expires_at", "consent_expires_at",
        "wallet_identity_id", "spending_grant_id",
    }
    assert body["wallet_identity_id"] is None
    assert body["spending_grant_id"] is None
    assert body["consent_expires_at"] is None
    assert isinstance(body["public_jwk_thumbprint"], str)
    assert len(body["public_jwk_thumbprint"]) == 43
    assert first["verification_uri"] not in result.text
    assert "no-store" in result.headers["cache-control"]
    # A supplied foreign selector cannot select or disclose that device.
    overridden = client.request("GET", "/account/opc/pairing", params={
        "pairing_id": second["pairing_id"],
    })
    assert overridden.json()["pairing"]["pairing_id"] == first["pairing_id"]
    other = client_for(account, opc, clock)
    exchange(other, second)
    assert get_context(other).json()["pairing"]["pairing_id"] == second["pairing_id"]
    _public_session(repository, user_id="ordinary", suffix="ordinary")
    client = client_for(account, opc, clock)
    client.cookies.set(SESSION_COOKIE, "browser-ordinary")
    client.cookies.set(CSRF_COOKIE, "csrf-ordinary")
    authenticate(client)
    assert get_context(client).json() == {"pairing": None}


@pytest.mark.parametrize("state", ["expired", "revoked"])
def test_context_never_advertises_expired_or_revoked_pairing_as_ready(tmp_path, state):
    clock, repository, account, opc = _context(tmp_path)
    pairing = _pair(opc, DeviceSigningKey.generate())
    client = client_for(account, opc, clock)
    exchange(client, pairing)
    with repository._write_session() as session:
        row = session.get(OpcPairingRow, pairing["pairing_id"])
        if state == "expired":
            row.expires_at = clock.value - timedelta(seconds=1)
        else:
            session.get(OpcInstallationRow, pairing["installation_id"]).status = "revoked"
    response = get_context(client)
    assert response.status_code == 200
    assert response.json()["pairing"]["status"] == state


@pytest.mark.parametrize("invalid", [None, "pairing_expired", "grant_paused", "consent_expired", "revoked"])
def test_context_active_requires_real_current_installation_authority(tmp_path, invalid):
    clock, repository, account, opc = _context(tmp_path)
    wallet = Account.create()
    identity = _identity(repository, wallet, user_id="existing")
    grant = _grant(repository, identity)
    installed = _attach_existing(opc, repository, DeviceSigningKey.generate(), wallet, identity, grant)
    client = client_for(account, opc, clock)
    client.cookies.set(SESSION_COOKIE, "browser-existing-existing")
    client.cookies.set(CSRF_COOKIE, "csrf-existing-existing")
    assert get_context(client).status_code == 401
    authenticate(client, wallet)
    if invalid == "pairing_expired":
        clock.value += timedelta(minutes=11)
    elif invalid == "grant_paused":
        repository.save_spending_grant(grant.model_copy(update={"status": "paused"}))
    elif invalid:
        with repository._write_session() as session:
            row = session.get(OpcInstallationRow, installed["installation_id"])
            if invalid == "revoked":
                row.status = "revoked"
            else:
                row.consent_expires_at = clock.value - timedelta(seconds=1)
    response = get_context(client)
    assert response.status_code == 200
    context = response.json()["pairing"]
    expected = "active" if invalid in {None, "pairing_expired"} else "revoked" if invalid == "revoked" else "consent_required"
    assert context["status"] == expected
    assert context["spending_grant_id"] == grant.spending_grant_id
    assert context["wallet_identity_id"] == identity.wallet_identity_id
    # Reading the context neither issues tokens nor changes grant budgets.
    assert opc.installation(installed["installation_id"])["status"] == ("revoked" if invalid == "revoked" else "active")
    assert repository.spending_grant(grant.spending_grant_id).max_amount_usdc == grant.max_amount_usdc


def test_multiple_pairings_for_one_session_fail_closed(tmp_path):
    clock, repository, account, opc = _context(tmp_path)
    first = _pair(opc, DeviceSigningKey.generate())
    second = _pair(opc, DeviceSigningKey.generate())
    client = client_for(account, opc, clock)
    exchange(client, first)
    with repository._write_session() as session:
        first_row = session.get(OpcPairingRow, first["pairing_id"])
        session.get(OpcPairingRow, second["pairing_id"]).public_account_session_id = first_row.public_account_session_id
    response = get_context(client)
    assert response.status_code == 409
    assert first["installation_id"] not in response.text
    assert second["installation_id"] not in response.text
