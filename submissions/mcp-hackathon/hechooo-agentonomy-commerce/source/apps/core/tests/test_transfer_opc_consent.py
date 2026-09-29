"""Transfer scope changes must not ride on an existing OPC device token."""
from decimal import Decimal

import pytest
from eth_account import Account
from eth_account.messages import encode_defunct

from services.account_service.schemas import SpendingGrantRequest
from shared.hosted_facilitator_protocol import DeviceSigningKey
from shared.opc_protocol import installation_id, sign_opc_proof
from test_opc_account import _context, _identity, _grant, _attach_existing, _pair, ORIGIN


def test_transfer_amendment_revokes_old_opc_token_until_new_wallet_consent(tmp_path):
    clock, repo, account, opc = _context(tmp_path)
    wallet = Account.create()
    identity = _identity(repo, wallet, user_id="transfer-opc")
    grant = _grant(repo, identity).model_copy(update={
        "product_scopes": ["marketplace"], "venue_scopes": ["clink_marketplace"],
        "used_amount_usdc": Decimal("1"), "reserved_amount_usdc": Decimal("0.5"),
    })
    repo.save_spending_grant(grant)
    key = DeviceSigningKey.generate()
    _attach_existing(opc, repo, key, wallet, identity, grant)

    def token(request_id):
        return opc.issue_token(sign_opc_proof(key, origin=ORIGIN, action="token",
            request_id=request_id, now=int(clock.value.timestamp())))["access_token"]

    old = token("before-transfer-scope")
    assert opc.authenticate_access_token(old)["user_id"] == identity.user_id
    fields = ("user_id", "wallet_identity_id", "agent_id", "max_amount_usdc",
              "per_transaction_limit_usdc", "hourly_limit_usdc", "daily_limit_usdc",
              "merchant_scopes", "merchant_trust_scopes", "notification_mode",
              "network_scopes", "asset_scopes", "starts_at", "expires_at")
    request = SpendingGrantRequest(**{field: getattr(grant, field) for field in fields},
        product_scopes=["marketplace", "transfers"],
        venue_scopes=["clink_marketplace", "clink_transfers"],
        amends_spending_grant_id=grant.spending_grant_id)
    challenge = account.create_spending_grant_challenge(request)
    assert "transfers" in challenge.message_to_sign
    signature = Account.sign_message(encode_defunct(text=challenge.message_to_sign), wallet.key).signature.hex()
    amended = account.create_spending_grant(request.model_copy(update={
        "session_id": challenge.session_id, "signed_message": challenge.message_to_sign,
        "signature": signature,
    }))
    assert amended.spending_grant_id == grant.spending_grant_id
    assert amended.used_amount_usdc == Decimal("1")
    assert amended.reserved_amount_usdc == Decimal("0.5")
    assert opc.installation(installation_id(key.public_jwk))["status"] == "consent_required"
    with pytest.raises(ValueError):
        opc.authenticate_access_token(old)
    with pytest.raises(ValueError):
        token("cannot-renew-before-consent")

    pairing = _pair(opc, key, request_id="transfer-fresh-consent")
    record = opc.pairing(pairing["pairing_id"])
    fresh = opc.create_installation_challenge(pairing["pairing_id"], user_id=identity.user_id,
        public_account_session_id=record["public_account_session_id"], spending_grant_id=grant.spending_grant_id)
    fresh_signature = Account.sign_message(encode_defunct(text=fresh["message_to_sign"]), wallet.key).signature.hex()
    assert opc.approve_installation(fresh["session_id"], fresh["message_to_sign"], fresh_signature)["status"] == "active"
    new = token("after-transfer-consent")
    assert opc.authenticate_access_token(new)["user_id"] == identity.user_id
    with pytest.raises(ValueError):
        opc.authenticate_access_token(old)
    assert repo.spending_grant(grant.spending_grant_id).product_scopes == ["marketplace", "transfers"]
