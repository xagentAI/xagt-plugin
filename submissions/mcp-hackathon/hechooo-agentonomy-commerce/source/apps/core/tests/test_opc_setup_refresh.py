from datetime import timedelta
from decimal import Decimal

import pytest
from eth_account import Account
from eth_account.messages import encode_defunct

from services.account_service.opc_service import OpcInstallationRow, OpcPairingRow
from services.account_service.repository import AccountSessionRow, PublicAccountSessionRow
from services.account_service.schemas import SpendingGrantRequest
from shared.hosted_facilitator_protocol import DeviceSigningKey
from shared.opc_protocol import sign_opc_proof
from test_opc_account import ORIGIN, _attach_existing, _context, _grant, _identity, _pair, _public_session


def sign(wallet, message):
    return Account.sign_message(encode_defunct(text=message), wallet.key).signature.hex()


def amend(account, wallet, grant, **changes):
    terms = grant.model_dump(exclude={
        "spending_grant_id", "status", "status_reason", "used_amount_usdc", "reserved_amount_usdc",
        "created_at", "updated_at",
    })
    request = SpendingGrantRequest(**{**terms, **changes}, amends_spending_grant_id=grant.spending_grant_id)
    challenge = account.create_spending_grant_challenge(request)
    return account.create_spending_grant(request.model_copy(update={
        "session_id": challenge.session_id, "signed_message": challenge.message_to_sign,
        "signature": sign(wallet, challenge.message_to_sign),
    }))


def attached(tmp_path):
    clock, repository, account, opc = _context(tmp_path)
    wallet = Account.create()
    identity = _identity(repository, wallet, user_id="refresh-user")
    grant = _grant(repository, identity).model_copy(update={
        "used_amount_usdc": Decimal("4"), "reserved_amount_usdc": Decimal("1"),
    })
    repository.save_spending_grant(grant)
    key = DeviceSigningKey.generate()
    installation = _attach_existing(opc, repository, key, wallet, identity, grant)
    context = opc.browser_pairing("public_existing-refresh-user")
    return clock, repository, account, opc, wallet, grant, key, installation, context


def challenge_for(opc, pairing, grant, **changes):
    args = {"user_id": grant.user_id, "public_account_session_id": "public_existing-refresh-user",
            "spending_grant_id": grant.spending_grant_id, **changes}
    return opc.create_installation_challenge(pairing["pairing_id"], **args)


def test_same_browser_pairing_can_refresh_amended_grant_without_resetting_budget(tmp_path):
    clock, repo, account, opc, wallet, grant, key, installation, pairing = attached(tmp_path)
    old_token = opc.issue_token(sign_opc_proof(key, origin=ORIGIN, action="token", request_id="old-token", now=int(clock.value.timestamp())))
    amend(account, wallet, grant, max_amount_usdc=Decimal("30"))
    assert opc.installation(installation["installation_id"])["status"] == "consent_required"
    with pytest.raises(ValueError):
        opc.authenticate_access_token(old_token["access_token"])
    fresh = challenge_for(opc, pairing, grant)
    assert "Grant Authorization Hash:" in fresh["message_to_sign"]
    restored = opc.approve_installation(fresh["session_id"], fresh["message_to_sign"], sign(wallet, fresh["message_to_sign"]))
    assert restored["status"] == "active"
    assert restored["spending_grant_id"] == grant.spending_grant_id
    stored = repo.spending_grant(grant.spending_grant_id)
    assert (stored.max_amount_usdc, stored.used_amount_usdc, stored.reserved_amount_usdc) == (30, 4, 1)
    with pytest.raises(ValueError):
        opc.authenticate_access_token(old_token["access_token"])
    new_token = opc.issue_token(sign_opc_proof(key, origin=ORIGIN, action="token", request_id="new-token", now=int(clock.value.timestamp())))
    assert opc.authenticate_access_token(new_token["access_token"])["spending_grant_id"] == grant.spending_grant_id


@pytest.mark.parametrize("invalid", ["grant", "user", "session", "expired", "revoked", "wallet"])
def test_linked_refresh_never_rebinds_or_revives_invalid_authority(tmp_path, invalid):
    clock, repo, account, opc, wallet, grant, _key, installation, pairing = attached(tmp_path)
    amend(account, wallet, grant, max_amount_usdc=Decimal("30"))
    args = {}
    if invalid == "grant":
        other = grant.model_copy(update={"spending_grant_id": "grant_other"})
        repo.save_spending_grant(other)
        args["spending_grant_id"] = other.spending_grant_id
    elif invalid == "user":
        args["user_id"] = "other-user"
    elif invalid == "session":
        other = _public_session(repo, user_id=grant.user_id, suffix="foreign")
        args["public_account_session_id"] = other.public_account_session_id
    else:
        foreign_identity = _identity(repo, Account.create(), user_id="foreign-wallet") if invalid == "wallet" else None
        with repo._write_session() as session:
            if invalid == "expired":
                session.get(OpcPairingRow, pairing["pairing_id"]).expires_at = clock.value - timedelta(seconds=1)
            elif invalid == "wallet":
                session.get(OpcInstallationRow, installation["installation_id"]).wallet_identity_id = foreign_identity.wallet_identity_id
            else:
                session.get(OpcInstallationRow, installation["installation_id"]).status = "revoked"
    with pytest.raises(ValueError):
        challenge_for(opc, pairing, grant, **args)


def test_device_signature_cannot_approve_a_grant_amended_after_challenge(tmp_path):
    _clock, repo, account, opc = _context(tmp_path)
    wallet = Account.create()
    identity = _identity(repo, wallet, user_id="pending-user")
    grant = _grant(repo, identity)
    pairing = _pair(opc, DeviceSigningKey.generate())
    browser = _public_session(repo, user_id=grant.user_id, suffix="pending")
    opc.claim_pairing(pairing["pairing_id"], user_id=grant.user_id, public_account_session_id=browser.public_account_session_id)
    old = challenge_for(opc, pairing, grant, public_account_session_id=browser.public_account_session_id)
    amend(account, wallet, grant, max_amount_usdc=Decimal("30"))
    with pytest.raises(ValueError, match="authority.*changed"):
        opc.approve_installation(old["session_id"], old["message_to_sign"], sign(wallet, old["message_to_sign"]))
    assert opc.installation(pairing["installation_id"])["status"] == "pending"


def test_usage_updates_do_not_invalidate_fresh_device_consent(tmp_path):
    _clock, repo, account, opc, wallet, grant, _key, _installation, pairing = attached(tmp_path)
    amend(account, wallet, grant, max_amount_usdc=Decimal("30"))
    fresh = challenge_for(opc, pairing, grant)
    current = repo.spending_grant(grant.spending_grant_id)
    repo.save_spending_grant(current.model_copy(update={"used_amount_usdc": Decimal("5"), "reserved_amount_usdc": Decimal("0")}))
    result = opc.approve_installation(fresh["session_id"], fresh["message_to_sign"], sign(wallet, fresh["message_to_sign"]))
    assert result["status"] == "active"


@pytest.mark.parametrize("invalid", ["session_revoked", "session_expired", "pairing_revoked", "binding_changed", "duplicate", "missing_hash"])
def test_refresh_revalidates_authority_after_wallet_signature(tmp_path, invalid):
    clock, repo, account, opc, wallet, grant, _key, installation, pairing = attached(tmp_path)
    amend(account, wallet, grant, max_amount_usdc=Decimal("30"))
    fresh = challenge_for(opc, pairing, grant)
    if invalid == "duplicate":
        opc.approve_installation(fresh["session_id"], fresh["message_to_sign"], sign(wallet, fresh["message_to_sign"]))
    else:
        if invalid == "binding_changed":
            foreign = _identity(repo, Account.create(), user_id="after-signature-foreign")
        with repo._write_session() as session:
            if invalid == "session_revoked":
                session.get(PublicAccountSessionRow, "public_existing-refresh-user").status = "revoked"
            elif invalid == "session_expired":
                session.get(PublicAccountSessionRow, "public_existing-refresh-user").expires_at = clock.value - timedelta(seconds=1)
            elif invalid == "pairing_revoked":
                session.get(OpcPairingRow, pairing["pairing_id"]).status = "revoked"
            elif invalid == "binding_changed":
                session.get(OpcInstallationRow, installation["installation_id"]).wallet_identity_id = foreign.wallet_identity_id
            else:
                row = session.get(AccountSessionRow, fresh["session_id"])
                row.payload = {k: v for k, v in row.payload.items() if k != "grant_authorization_hash"}
                row.payload_hash = account._payload_hash(row.payload)
                fresh["message_to_sign"] = opc._canonical_installation_message(repo._account_session(row))
    with pytest.raises(ValueError):
        opc.approve_installation(fresh["session_id"], fresh["message_to_sign"], sign(wallet, fresh["message_to_sign"]))
    assert opc.installation(installation["installation_id"])["status"] == ("active" if invalid == "duplicate" else "consent_required")
