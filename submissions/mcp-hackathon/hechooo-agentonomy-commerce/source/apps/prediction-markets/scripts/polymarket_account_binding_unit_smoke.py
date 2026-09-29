from __future__ import annotations

import tempfile
from pathlib import Path

import sys
from eth_account import Account
from eth_account.messages import encode_defunct
from pydantic import ValidationError

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from services.account_binding_service.schemas import (  # noqa: E402
    CompletePolymarketBindingSessionRequest,
    CreatePolymarketBindingSessionRequest,
    PolymarketAccountBinding,
    PolymarketBindingSession,
)
from services.account_binding_service.credential_store import (  # noqa: E402
    PolymarketApiCredentials,
)
from services.account_binding_service.service import PolymarketAccountBindingService  # noqa: E402
from shared.config import AppConfig  # noqa: E402


class FakeClobAuthClient:
    def get_server_time(self) -> str:
        return "1780000000"

    def derive_api_credentials(self, *, wallet_address: str, signature: str, timestamp: str, nonce: int) -> dict:
        assert signature == "0xclobauth"
        return {"apiKey": "pm-key", "secret": "pm-secret", "passphrase": "pm-passphrase"}


CHECKSUM_DEPOSIT_WALLET = "0x52908400098527886E0F7030069857D2E4169EE7"
NORMALIZED_DEPOSIT_WALLET = CHECKSUM_DEPOSIT_WALLET.lower()
ZERO_ADDRESS = "0x" + "0" * 40


def _deposit_wallet_model_factories(value: object):
    return (
        lambda: CreatePolymarketBindingSessionRequest(
            user_id="schema-user",
            polymarket_deposit_wallet=value,
        ),
        lambda: CompletePolymarketBindingSessionRequest(
            wallet_address="0x1111111111111111111111111111111111111111",
            signature="0xsig",
            signed_message="message",
            polymarket_deposit_wallet=value,
        ),
        lambda: PolymarketBindingSession(
            session_id="pm_bind_sess_schema",
            user_id="schema-user",
            agent_id="hermes",
            polymarket_deposit_wallet=value,
            message_to_sign="message",
            signing_url="https://example.test/session",
            status="pending",
            next_action="open_polymarket_binding_console",
            expires_at="2099-01-01T00:00:00Z",
            created_at="2026-08-21T00:00:00Z",
        ),
        lambda: PolymarketAccountBinding(
            binding_id="pm_binding_schema",
            session_id="pm_bind_sess_schema",
            user_id="schema-user",
            agent_id="hermes",
            wallet_address="0x1111111111111111111111111111111111111111",
            polymarket_deposit_wallet=value,
            funder_address="0x1111111111111111111111111111111111111111",
            status="active",
            next_action="account_binding_active",
            created_at="2026-08-21T00:00:00Z",
        ),
    )


def _owner_wallet_model_factories(value: object):
    return (
        lambda: CreatePolymarketBindingSessionRequest(
            user_id="schema-user",
            wallet_address=value,
        ),
        lambda: CompletePolymarketBindingSessionRequest(
            wallet_address=value,
            signature="0xsig",
            signed_message="message",
        ),
        lambda: PolymarketBindingSession(
            session_id="pm_bind_sess_schema",
            user_id="schema-user",
            agent_id="hermes",
            wallet_address=value,
            message_to_sign="message",
            signing_url="https://example.test/session",
            status="pending",
            next_action="open_polymarket_binding_console",
            expires_at="2099-01-01T00:00:00Z",
            created_at="2026-08-21T00:00:00Z",
        ),
        lambda: PolymarketAccountBinding(
            binding_id="pm_binding_schema",
            session_id="pm_bind_sess_schema",
            user_id="schema-user",
            agent_id="hermes",
            wallet_address=value,
            status="active",
            next_action="account_binding_active",
            created_at="2026-08-21T00:00:00Z",
        ),
    )


def _funder_address_model_factory(value: object):
    return lambda: PolymarketAccountBinding(
        binding_id="pm_binding_schema",
        session_id="pm_bind_sess_schema",
        user_id="schema-user",
        agent_id="hermes",
        wallet_address="0x1111111111111111111111111111111111111111",
        funder_address=value,
        status="active",
        next_action="account_binding_active",
        created_at="2026-08-21T00:00:00Z",
    )


def _assert_validation_error(factory, field_name: str) -> None:
    try:
        factory()
    except ValidationError as exc:
        assert field_name in str(exc)
        return
    raise AssertionError("invalid EVM address must fail Pydantic validation")


def _save_test_credentials(
    service: PolymarketAccountBindingService,
    *,
    user_id: str,
    wallet_address: str,
) -> None:
    service.credential_store.save_polymarket_credentials(
        user_id=user_id,
        wallet_address=wallet_address,
        credentials=PolymarketApiCredentials(
            api_key=f"{user_id}-key",
            api_secret=f"{user_id}-secret",
            api_passphrase=f"{user_id}-passphrase",
            signature_type="3",
            funder_address=NORMALIZED_DEPOSIT_WALLET,
        ),
        credential_source="unit_smoke",
    )


def main() -> None:
    for invalid_address in ("", "0x1234", ZERO_ADDRESS, 123):
        for factory in _deposit_wallet_model_factories(invalid_address):
            _assert_validation_error(factory, "polymarket_deposit_wallet")
        for factory in _owner_wallet_model_factories(invalid_address):
            _assert_validation_error(factory, "wallet_address")
        _assert_validation_error(
            _funder_address_model_factory(invalid_address),
            "funder_address",
        )

    for factory in _deposit_wallet_model_factories(CHECKSUM_DEPOSIT_WALLET):
        assert factory().polymarket_deposit_wallet == NORMALIZED_DEPOSIT_WALLET
    for factory in _owner_wallet_model_factories(CHECKSUM_DEPOSIT_WALLET):
        assert factory().wallet_address == NORMALIZED_DEPOSIT_WALLET
    assert (
        _funder_address_model_factory(CHECKSUM_DEPOSIT_WALLET)().funder_address
        == NORMALIZED_DEPOSIT_WALLET
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        config = AppConfig(
            account_binding_file=str(Path(tmpdir) / "polymarket_bindings.jsonl"),
            credential_store_file=str(Path(tmpdir) / "polymarket_credentials.jsonl"),
            account_binding_console_base_url="http://127.0.0.1:8047",
        )
        service = PolymarketAccountBindingService(config=config, clob_auth_client=FakeClobAuthClient())
        wallet = Account.create()
        session_deposit_wallet = CHECKSUM_DEPOSIT_WALLET

        session = service.create_binding_session(
            CreatePolymarketBindingSessionRequest(
                user_id="user-1",
                agent_id="hermes",
                wallet_address=wallet.address,
                polymarket_deposit_wallet=session_deposit_wallet,
                expires_in_minutes=30,
            )
        )
        assert session.status == "pending"
        assert (
            f"/polymarket/binding-console/{session.session_id}?access_token="
            in session.signing_url
        )
        persisted = service.get_binding_session(session.session_id)
        assert persisted is not None
        assert "access_token=" not in persisted.signing_url
        assert "Polymarket Account Binding" in session.message_to_sign
        assert session.wallet_address == wallet.address.lower()
        assert session.polymarket_deposit_wallet == NORMALIZED_DEPOSIT_WALLET

        historical_session_payload = session.model_dump()
        historical_session_payload.update(
            {
                "session_id": "pm_bind_sess_historical_checksum",
                "wallet_address": wallet.address,
                "polymarket_deposit_wallet": CHECKSUM_DEPOSIT_WALLET,
            }
        )
        service._save_record(
            "session",
            historical_session_payload["session_id"],
            historical_session_payload,
        )
        historical_session = service.get_binding_session(
            historical_session_payload["session_id"]
        )
        assert historical_session is not None
        assert historical_session.wallet_address == wallet.address.lower()
        assert (
            historical_session.polymarket_deposit_wallet
            == NORMALIZED_DEPOSIT_WALLET
        )

        bad = service.complete_binding_session(
            session.session_id,
            CompletePolymarketBindingSessionRequest(
                wallet_address=wallet.address,
                signature="0xdeadbeef",
                signed_message=session.message_to_sign,
            ),
        )
        assert bad.status == "signature_failed"
        assert bad.next_action == "retry_wallet_signature"
        assert bad.binding_id is None

        signature = Account.sign_message(encode_defunct(text=session.message_to_sign), wallet.key).signature.hex()
        completed = service.complete_binding_session(
            session.session_id,
            CompletePolymarketBindingSessionRequest(
                wallet_address=wallet.address,
                signature=signature,
                signed_message=session.message_to_sign,
                clob_auth_signature="0xclobauth",
                clob_auth_timestamp="1780000000",
                clob_auth_nonce=0,
            ),
        )
        assert completed.status == "completed"
        assert completed.binding_id is not None
        assert completed.next_action == "account_binding_active"

        binding = service.get_binding(completed.binding_id)
        assert binding is not None
        assert binding.status == "active"
        assert binding.wallet_address == wallet.address.lower()
        assert binding.account_mode == "deposit_wallet"
        assert binding.polymarket_signature_type == "3"
        assert binding.polymarket_deposit_wallet == NORMALIZED_DEPOSIT_WALLET
        assert binding.funder_address == NORMALIZED_DEPOSIT_WALLET
        assert binding.metadata["deposit_wallet_source"] == "session"
        assert binding.metadata["account_source"] == "session"
        assert binding.has_api_credentials is True
        assert binding.signature_scheme == "eip191_personal_sign"

        historical_binding_payload = binding.model_dump()
        historical_binding_payload.update(
            {
                "binding_id": "pm_binding_historical_checksum",
                "user_id": "historical-user",
                "wallet_address": wallet.address,
                "polymarket_deposit_wallet": CHECKSUM_DEPOSIT_WALLET,
                "funder_address": CHECKSUM_DEPOSIT_WALLET,
            }
        )
        service._save_record(
            "binding",
            historical_binding_payload["binding_id"],
            historical_binding_payload,
        )
        historical_binding = service.get_binding(
            historical_binding_payload["binding_id"]
        )
        assert historical_binding is not None
        assert historical_binding.wallet_address == wallet.address.lower()
        assert (
            historical_binding.polymarket_deposit_wallet
            == NORMALIZED_DEPOSIT_WALLET
        )
        assert historical_binding.funder_address == NORMALIZED_DEPOSIT_WALLET

        reset_user = "ordered-reset-user"
        _save_test_credentials(
            service,
            user_id=reset_user,
            wallet_address=wallet.address,
        )
        reset_valid_old = binding.model_dump()
        reset_valid_old.update(
            {
                "binding_id": "pm_binding_reset_valid_old",
                "user_id": reset_user,
            }
        )
        reset_malformed_new = binding.model_dump()
        reset_malformed_new.update(
            {
                "binding_id": "pm_binding_reset_malformed_new",
                "user_id": reset_user,
                "wallet_address": "malformed",
            }
        )
        for raw_binding in (reset_valid_old, reset_malformed_new):
            service._save_record(
                "binding",
                raw_binding["binding_id"],
                raw_binding,
            )

        recover_user = "ordered-recover-user"
        _save_test_credentials(
            service,
            user_id=recover_user,
            wallet_address=wallet.address,
        )
        recover_valid_old = binding.model_dump()
        recover_valid_old.update(
            {
                "binding_id": "pm_binding_recover_valid_old",
                "user_id": recover_user,
            }
        )
        recover_malformed_mid = binding.model_dump()
        recover_malformed_mid.update(
            {
                "binding_id": "pm_binding_recover_malformed_mid",
                "user_id": recover_user,
                "funder_address": ZERO_ADDRESS,
            }
        )
        recover_valid_new = binding.model_dump()
        recover_valid_new.update(
            {
                "binding_id": "pm_binding_recover_valid_new",
                "user_id": recover_user,
            }
        )
        other_user_malformed = binding.model_dump()
        other_user_malformed.update(
            {
                "binding_id": "pm_binding_other_user_malformed_new",
                "user_id": "unrelated-user",
                "wallet_address": "malformed",
            }
        )
        for raw_binding in (
            recover_valid_old,
            recover_malformed_mid,
            recover_valid_new,
            other_user_malformed,
        ):
            service._save_record(
                "binding",
                raw_binding["binding_id"],
                raw_binding,
            )

        ordered_history_before = service.storage_file.read_bytes()
        assert service.latest_binding(reset_user, "polymarket") is None
        recovered_latest = service.latest_binding(recover_user, "polymarket")
        assert recovered_latest is not None
        assert recovered_latest.binding_id == "pm_binding_recover_valid_new"
        assert service.storage_file.read_bytes() == ordered_history_before

        malformed_other_user = binding.model_dump()
        malformed_other_user.update(
            {
                "binding_id": "pm_binding_malformed_other_user",
                "user_id": "other-user",
                "wallet_address": "malformed",
            }
        )
        malformed_other_venue = binding.model_dump()
        malformed_other_venue.update(
            {
                "binding_id": "pm_binding_malformed_other_venue",
                "venue": "other-venue",
                "wallet_address": ZERO_ADDRESS,
            }
        )
        malformed_target = binding.model_dump()
        malformed_target.update(
            {
                "binding_id": "pm_binding_malformed_target",
                "wallet_address": "0x1234",
            }
        )
        newer_binding_id = "pm_binding_newer_valid"
        newer_valid = binding.model_dump()
        newer_valid["binding_id"] = newer_binding_id
        for raw_binding in (
            malformed_other_user,
            malformed_other_venue,
            malformed_target,
            newer_valid,
        ):
            service._save_record(
                "binding",
                raw_binding["binding_id"],
                raw_binding,
            )

        binding_history_before = service.storage_file.read_bytes()
        latest = service.latest_binding("user-1", "polymarket")
        assert latest is not None
        assert latest.binding_id == newer_binding_id
        assert service.storage_file.read_bytes() == binding_history_before

        malformed_only_user = "malformed-only-user"
        service.credential_store.save_polymarket_credentials(
            user_id=malformed_only_user,
            wallet_address=wallet.address,
            credentials=PolymarketApiCredentials(
                api_key="malformed-only-key",
                api_secret="malformed-only-secret",
                api_passphrase="malformed-only-passphrase",
                signature_type="3",
                funder_address=NORMALIZED_DEPOSIT_WALLET,
            ),
            credential_source="unit_smoke",
        )
        malformed_only = binding.model_dump()
        malformed_only.update(
            {
                "binding_id": "pm_binding_malformed_only",
                "user_id": malformed_only_user,
                "funder_address": ZERO_ADDRESS,
            }
        )
        service._save_record(
            "binding",
            malformed_only["binding_id"],
            malformed_only,
        )
        malformed_history_before = service.storage_file.read_bytes()
        assert service.latest_binding(malformed_only_user, "polymarket") is None
        assert service.storage_file.read_bytes() == malformed_history_before

        assert service.credential_store.get_polymarket_credentials("user-1") is not None

        second_session = service.create_binding_session(
            CreatePolymarketBindingSessionRequest(
                user_id="user-1",
                agent_id="hermes",
                wallet_address=wallet.address,
                expires_in_minutes=30,
            )
        )
        assert second_session.binding_id == newer_binding_id
        second_signature = Account.sign_message(encode_defunct(text=second_session.message_to_sign), wallet.key).signature.hex()
        second_completed = service.complete_binding_session(
            second_session.session_id,
            CompletePolymarketBindingSessionRequest(
                wallet_address=wallet.address,
                signature=second_signature,
                signed_message=second_session.message_to_sign,
                clob_auth_signature="0xclobauth",
                clob_auth_timestamp="1780000000",
                clob_auth_nonce=0,
            ),
        )
        assert second_completed.binding_id is not None
        second_binding = service.get_binding(second_completed.binding_id)
        assert second_binding is not None
        assert second_binding.account_mode == "eoa"
        assert second_binding.polymarket_signature_type == "0"
        assert second_binding.polymarket_deposit_wallet is None
        assert second_binding.wallet_address == wallet.address.lower()
        assert second_binding.funder_address == wallet.address.lower()
        assert service.latest_binding("user-1", "polymarket").binding_id == second_completed.binding_id

        revoked = service.revoke_binding(
            second_completed.binding_id,
            reason="user_requested_unbind",
            metadata={"source": "unit_smoke"},
        )
        assert revoked.status == "revoked"
        assert revoked.next_action == "create_polymarket_account_binding"
        assert revoked.reason == "user_requested_unbind"
        assert revoked.metadata["credential_store_deleted"] is True
        assert service.latest_binding("user-1", "polymarket") is None
        assert service.credential_store.get_polymarket_credentials("user-1") is None

        bypass_wallet = Account.create()
        bypass_session = service.create_binding_session(
            CreatePolymarketBindingSessionRequest(
                user_id="bypass-user",
                wallet_address=bypass_wallet.address,
            )
        )
        bypass_signature = Account.sign_message(
            encode_defunct(text=bypass_session.message_to_sign),
            bypass_wallet.key,
        ).signature.hex()
        bypass_request = CompletePolymarketBindingSessionRequest.model_construct(
            wallet_address=bypass_wallet.address,
            signature=bypass_signature,
            signed_message=bypass_session.message_to_sign,
            polymarket_deposit_wallet="0x1234",
            clob_auth_signature="0xclobauth",
            clob_auth_timestamp="1780000000",
            clob_auth_nonce=0,
            polymarket_signature_type="3",
            metadata={},
        )
        try:
            service.complete_binding_session(
                bypass_session.session_id,
                bypass_request,
            )
        except ValidationError:
            pass
        else:
            raise AssertionError(
                "direct service completion must revalidate Deposit Wallet"
            )
        persisted_bypass_session = service.get_binding_session(
            bypass_session.session_id
        )
        assert persisted_bypass_session is not None
        assert persisted_bypass_session.status == "pending"
        assert persisted_bypass_session.binding_id is None
        assert (
            service.credential_store.get_polymarket_credentials("bypass-user")
            is None
        )
        assert service.latest_binding("bypass-user", "polymarket") is None

        print(
            {
                "status": "ok",
                "session_id": session.session_id,
                "binding_id": revoked.binding_id,
                "binding_status": revoked.status,
            }
        )


if __name__ == "__main__":
    main()
