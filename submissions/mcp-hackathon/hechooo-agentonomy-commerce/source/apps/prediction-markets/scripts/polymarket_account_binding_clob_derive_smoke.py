from __future__ import annotations

import tempfile
from pathlib import Path

import sys
from cryptography.fernet import Fernet
from eth_account import Account
from eth_account.messages import encode_defunct
from pydantic import ValidationError

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from services.account_binding_service.schemas import (  # noqa: E402
    CompletePolymarketBindingSessionRequest,
    CreatePolymarketBindingSessionRequest,
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
        assert wallet_address.startswith("0x")
        assert signature == "0xclobauth"
        assert timestamp == "1780000000"
        assert nonce == 0
        return {
            "apiKey": "derived-key",
            "secret": "derived-secret",
            "passphrase": "derived-passphrase",
            "funderAddress": "0x1111111111111111111111111111111111111111",
        }


class FakeClobAuthClientWithoutDepositWallet:
    def get_server_time(self) -> str:
        return "1780000000"

    def derive_api_credentials(self, *, wallet_address: str, signature: str, timestamp: str, nonce: int) -> dict:
        return {"apiKey": "derived-key-2", "secret": "derived-secret-2", "passphrase": "derived-passphrase-2"}


class FakeClobAuthClientWithAddress:
    def __init__(self, address_payload: dict[str, object]) -> None:
        self.address_payload = address_payload

    def get_server_time(self) -> str:
        return "1780000000"

    def derive_api_credentials(self, *, wallet_address: str, signature: str, timestamp: str, nonce: int) -> dict:
        return {
            "apiKey": "replacement-key",
            "secret": "replacement-secret",
            "passphrase": "replacement-passphrase",
            **self.address_payload,
        }


def _assert_invalid_derived_address_fails_closed(
    tmpdir: str,
    *,
    case_name: str,
    address_payload: dict[str, object],
) -> None:
    credential_file = Path(tmpdir) / f"credentials_{case_name}.jsonl"
    service = PolymarketAccountBindingService(
        config=AppConfig(
            account_binding_file=str(
                Path(tmpdir) / f"polymarket_bindings_{case_name}.jsonl"
            ),
            credential_store_file=str(credential_file),
            credential_encryption_key=Fernet.generate_key().decode("utf-8"),
            account_binding_console_base_url="http://127.0.0.1:8047",
        ),
        clob_auth_client=FakeClobAuthClientWithAddress(address_payload),
    )
    wallet = Account.create()
    user_id = f"user-invalid-{case_name}"
    service.credential_store.save_polymarket_credentials(
        user_id=user_id,
        wallet_address=wallet.address,
        credentials=PolymarketApiCredentials(
            api_key="existing-key",
            api_secret="existing-secret",
            api_passphrase="existing-passphrase",
            signature_type="0",
            funder_address=wallet.address,
        ),
        credential_source="clob_derive_smoke",
    )
    credentials_before = credential_file.read_bytes()
    session = service.create_binding_session(
        CreatePolymarketBindingSessionRequest(
            user_id=user_id,
            agent_id="hermes",
            wallet_address=wallet.address,
        )
    )
    bindings_before = service.storage_file.read_bytes()
    signature = Account.sign_message(
        encode_defunct(text=session.message_to_sign),
        wallet.key,
    ).signature.hex()

    try:
        service.complete_binding_session(
            session.session_id,
            CompletePolymarketBindingSessionRequest(
                wallet_address=wallet.address,
                signature=signature,
                signed_message=session.message_to_sign,
                clob_auth_signature="0xclobauth",
                clob_auth_timestamp="1780000000",
                clob_auth_nonce=0,
                polymarket_signature_type="3",
            ),
        )
    except (ValidationError, ValueError) as exc:
        assert "address" in str(exc).lower()
    else:
        raise AssertionError("invalid CLOB-derived address must fail completion")

    assert credential_file.read_bytes() == credentials_before
    assert service.storage_file.read_bytes() == bindings_before
    assert service.latest_binding(user_id) is None
    persisted_session = service.get_binding_session(session.session_id)
    assert persisted_session is not None
    assert persisted_session.status == "pending"
    assert persisted_session.binding_id is None


def main() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        config = AppConfig(
            account_binding_file=str(Path(tmpdir) / "polymarket_bindings.jsonl"),
            credential_store_file=str(Path(tmpdir) / "credentials.jsonl"),
            credential_encryption_key=Fernet.generate_key().decode("utf-8"),
            account_binding_console_base_url="http://127.0.0.1:8047",
        )
        service = PolymarketAccountBindingService(config=config, clob_auth_client=FakeClobAuthClient())
        wallet = Account.create()
        session = service.create_binding_session(
            CreatePolymarketBindingSessionRequest(
                user_id="user-derive",
                agent_id="hermes",
                wallet_address=wallet.address,
            )
        )
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
                polymarket_signature_type="3",
            ),
        )

        assert completed.status == "completed"
        binding = service.get_binding(completed.binding_id)
        assert binding is not None
        assert binding.status == "active"
        assert binding.polymarket_deposit_wallet == "0x1111111111111111111111111111111111111111"
        assert binding.metadata["deposit_wallet_source"] == "clob_auth_response"
        assert binding.has_api_credentials is True
        assert binding.metadata["credential_source"] == "polymarket_l1_derive"

        credentials = service.credential_store.get_polymarket_credentials("user-derive")
        assert credentials is not None
        assert credentials.api_key == "derived-key"
        assert credentials.api_secret == "derived-secret"
        assert credentials.api_passphrase == "derived-passphrase"

        service_without_deposit = PolymarketAccountBindingService(
            config=AppConfig(
                account_binding_file=str(Path(tmpdir) / "polymarket_bindings_missing_deposit.jsonl"),
                credential_store_file=str(Path(tmpdir) / "credentials_missing_deposit.jsonl"),
                credential_encryption_key=Fernet.generate_key().decode("utf-8"),
                account_binding_console_base_url="http://127.0.0.1:8047",
            ),
            clob_auth_client=FakeClobAuthClientWithoutDepositWallet(),
        )
        wallet_2 = Account.create()
        session_2 = service_without_deposit.create_binding_session(
            CreatePolymarketBindingSessionRequest(user_id="user-missing-deposit", agent_id="hermes", wallet_address=wallet_2.address)
        )
        signature_2 = Account.sign_message(encode_defunct(text=session_2.message_to_sign), wallet_2.key).signature.hex()
        completed_2 = service_without_deposit.complete_binding_session(
            session_2.session_id,
            CompletePolymarketBindingSessionRequest(
                wallet_address=wallet_2.address,
                signature=signature_2,
                signed_message=session_2.message_to_sign,
                clob_auth_signature="0xclobauth",
                clob_auth_timestamp="1780000000",
                clob_auth_nonce=0,
                polymarket_signature_type="auto",
            ),
        )
        assert completed_2.next_action == "account_binding_active"
        binding_2 = service_without_deposit.get_binding(completed_2.binding_id)
        assert binding_2 is not None
        assert binding_2.status == "active"
        assert binding_2.next_action == "account_binding_active"
        assert binding_2.polymarket_signature_type == "0"
        assert binding_2.metadata["account_mode"] == "eoa"
        assert binding_2.has_api_credentials is True
        assert binding_2.polymarket_deposit_wallet is None
        credentials_2 = service_without_deposit.credential_store.get_polymarket_credentials("user-missing-deposit")
        assert credentials_2 is not None
        assert credentials_2.signature_type == "0"
        assert credentials_2.funder_address == wallet_2.address.lower()

        address_a = "0x1111111111111111111111111111111111111111"
        address_b = "0x2222222222222222222222222222222222222222"
        mixed_case = "0x52908400098527886E0F7030069857D2E4169EE7"
        for case_name, address_payload in (
            (
                "conflicting_top_level",
                {"funderAddress": address_a, "depositWallet": address_b},
            ),
            (
                "malformed_nested",
                {
                    "funderAddress": address_a,
                    "account": {"depositWallet": "0x" + "z" * 40},
                },
            ),
            (
                "conflicting_nested",
                {
                    "funderAddress": address_a,
                    "profile": {"proxyWallet": address_b},
                },
            ),
            ("malformed_deposit", {"depositWallet": "0x" + "z" * 40}),
            ("zero_proxy", {"proxyWallet": "0x" + "0" * 40}),
            ("non_string_safe", {"safeAddress": 123}),
        ):
            _assert_invalid_derived_address_fails_closed(
                tmpdir,
                case_name=case_name,
                address_payload=address_payload,
            )

        assert PolymarketAccountBindingService._extract_deposit_wallet(
            {
                "funderAddress": mixed_case,
                "user": {"safeAddress": mixed_case.lower()},
            }
        ) == mixed_case.lower()
        assert PolymarketAccountBindingService._extract_deposit_wallet(
            {"account": {"proxyWallet": mixed_case}}
        ) == mixed_case.lower()
        assert PolymarketAccountBindingService._extract_deposit_wallet(
            {"wallet": address_a}
        ) is None

        print({"status": "ok", "binding_id": binding.binding_id, "source": binding.metadata["credential_source"]})


if __name__ == "__main__":
    main()
