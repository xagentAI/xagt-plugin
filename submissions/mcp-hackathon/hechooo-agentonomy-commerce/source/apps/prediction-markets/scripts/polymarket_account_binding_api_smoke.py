from __future__ import annotations

import tempfile
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import sys
from eth_account import Account
from eth_account.messages import encode_defunct
from fastapi.testclient import TestClient

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import services.account_binding_service.app as account_binding_app  # noqa: E402
from services.account_binding_service.service import PolymarketAccountBindingService  # noqa: E402
from shared.config import AppConfig  # noqa: E402


CHECKSUM_DEPOSIT_WALLET = "0x52908400098527886E0F7030069857D2E4169EE7"
ZERO_ADDRESS = "0x" + "0" * 40


class FakeClobAuthClient:
    def get_server_time(self) -> str:
        return "1780000000"

    def derive_api_credentials(self, *, wallet_address: str, signature: str, timestamp: str, nonce: int) -> dict:
        assert signature == "0xclobauth"
        return {"apiKey": "pm-key", "secret": "pm-secret", "passphrase": "pm-passphrase"}


class FakeCoreAccountClient:
    def __init__(self, wallet_address: str):
        self.wallet_address = wallet_address

    def readiness(self, user_id: str) -> dict:
        if user_id == "unbound-user":
            return {
                "user_id": user_id,
                "wallet_bound": False,
                "wallet_address": None,
                "spending_grant_active": False,
                "ready": False,
            }
        return {
            "user_id": user_id,
            "wallet_bound": True,
            "wallet_address": self.wallet_address,
            "spending_grant_active": True,
            "ready": True,
        }


def main() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        account_binding_app.CONFIG = AppConfig(
            account_binding_file=str(Path(tmpdir) / "bindings.jsonl"),
            credential_store_file=str(Path(tmpdir) / "credentials.jsonl"),
            account_binding_console_base_url="http://127.0.0.1:8047",
            clink_core_internal_api_token="test-internal-token",
        )
        account_binding_app.SERVICE = PolymarketAccountBindingService(account_binding_app.CONFIG, clob_auth_client=FakeClobAuthClient())
        wallet = Account.create()
        other_wallet = Account.create()
        account_binding_app.CORE_ACCOUNT_CLIENT = FakeCoreAccountClient(wallet.address)
        client = TestClient(account_binding_app.APP)
        internal_headers = {"Authorization": "Bearer test-internal-token"}

        public_create = client.post(
            "/polymarket/binding-sessions",
            json={"user_id": "api-user", "agent_id": "hermes"},
        )
        assert public_create.status_code == 404
        unauthorized_create = client.post(
            "/internal/polymarket/binding-sessions",
            json={"user_id": "api-user", "agent_id": "hermes"},
        )
        assert unauthorized_create.status_code == 401

        unbound = client.post(
            "/internal/polymarket/binding-sessions",
            headers=internal_headers,
            json={"user_id": "unbound-user", "agent_id": "hermes"},
        )
        assert unbound.status_code == 409
        assert unbound.json()["detail"] == "Core Account wallet binding is required"

        wrong_create = client.post(
            "/internal/polymarket/binding-sessions",
            headers=internal_headers,
            json={
                "user_id": "api-user",
                "agent_id": "hermes",
                "wallet_address": other_wallet.address,
            },
        )
        assert wrong_create.status_code == 409
        assert wrong_create.json()["detail"] == "Selected wallet does not match the active Core wallet"

        invalid_deposit_wallets = ("", "0x1234", ZERO_ADDRESS, 123)
        for index, invalid_deposit_wallet in enumerate(
            invalid_deposit_wallets
        ):
            sessions_before = set(
                account_binding_app.SERVICE._load_latest("session")
            )
            invalid_create = client.post(
                "/internal/polymarket/binding-sessions",
                headers=internal_headers,
                json={
                    "user_id": f"invalid-create-user-{index}",
                    "agent_id": "hermes",
                    "polymarket_deposit_wallet": invalid_deposit_wallet,
                },
            )
            assert invalid_create.status_code == 422
            assert set(
                account_binding_app.SERVICE._load_latest("session")
            ) == sessions_before

        for index, invalid_wallet_address in enumerate(
            invalid_deposit_wallets
        ):
            sessions_before = set(
                account_binding_app.SERVICE._load_latest("session")
            )
            invalid_wallet_create = client.post(
                "/internal/polymarket/binding-sessions",
                headers=internal_headers,
                json={
                    "user_id": f"invalid-wallet-create-user-{index}",
                    "agent_id": "hermes",
                    "wallet_address": invalid_wallet_address,
                },
            )
            assert invalid_wallet_create.status_code == 422
            assert set(
                account_binding_app.SERVICE._load_latest("session")
            ) == sessions_before

        created = client.post(
            "/internal/polymarket/binding-sessions",
            headers=internal_headers,
            json={
                "user_id": "api-user",
                "agent_id": "hermes",
            },
        )
        assert created.status_code == 200
        session = created.json()
        assert "console_token_hash" not in session["metadata"]
        parsed_signing_url = urlparse(session["signing_url"])
        console_token = parse_qs(parsed_signing_url.query)["access_token"][0]
        missing_console_token = client.get(parsed_signing_url.path)
        assert missing_console_token.status_code == 401
        invalid_console_token = client.get(
            f"{parsed_signing_url.path}?access_token={'x' * 32}"
        )
        assert invalid_console_token.status_code == 401
        assert session["status"] == "pending"
        assert session["wallet_address"] == wallet.address.lower()

        wrong_completion = client.post(
            f"/polymarket/binding-sessions/{session['session_id']}/complete",
            headers={"X-Clink-Console-Token": console_token},
            json={
                "wallet_address": other_wallet.address,
                "signature": "0xwrong",
                "signed_message": session["message_to_sign"],
                "clob_auth_signature": "0xclobauth",
                "clob_auth_timestamp": "1780000000",
                "clob_auth_nonce": 0,
            },
        )
        assert wrong_completion.status_code == 409
        assert wrong_completion.json()["detail"] == "Selected wallet does not match the active Core wallet"

        for invalid_wallet_address in invalid_deposit_wallets:
            invalid_wallet_complete = client.post(
                f"/polymarket/binding-sessions/{session['session_id']}/complete",
                headers={"X-Clink-Console-Token": console_token},
                json={
                    "wallet_address": invalid_wallet_address,
                    "signature": "0xwrong",
                    "signed_message": session["message_to_sign"],
                },
            )
            assert invalid_wallet_complete.status_code == 422
            unchanged_session = account_binding_app.SERVICE.get_binding_session(
                session["session_id"]
            )
            assert unchanged_session is not None
            assert unchanged_session.status == "pending"
            assert unchanged_session.binding_id is None

        for index, invalid_deposit_wallet in enumerate(
            invalid_deposit_wallets
        ):
            invalid_user_id = f"invalid-complete-user-{index}"
            invalid_session_response = client.post(
                "/internal/polymarket/binding-sessions",
                headers=internal_headers,
                json={
                    "user_id": invalid_user_id,
                    "agent_id": "hermes",
                },
            )
            assert invalid_session_response.status_code == 200
            invalid_session = invalid_session_response.json()
            invalid_url = urlparse(invalid_session["signing_url"])
            invalid_console_token = parse_qs(invalid_url.query)[
                "access_token"
            ][0]
            invalid_signature = Account.sign_message(
                encode_defunct(text=invalid_session["message_to_sign"]),
                wallet.key,
            ).signature.hex()
            invalid_complete = client.post(
                (
                    "/polymarket/binding-sessions/"
                    f"{invalid_session['session_id']}/complete"
                ),
                headers={"X-Clink-Console-Token": invalid_console_token},
                json={
                    "wallet_address": wallet.address,
                    "signature": invalid_signature,
                    "signed_message": invalid_session["message_to_sign"],
                    "polymarket_deposit_wallet": invalid_deposit_wallet,
                    "clob_auth_signature": "0xclobauth",
                    "clob_auth_timestamp": "1780000000",
                    "clob_auth_nonce": 0,
                    "polymarket_signature_type": "3",
                },
            )
            assert invalid_complete.status_code == 422
            persisted_invalid_session = (
                account_binding_app.SERVICE.get_binding_session(
                    invalid_session["session_id"]
                )
            )
            assert persisted_invalid_session is not None
            assert persisted_invalid_session.status == "pending"
            assert persisted_invalid_session.binding_id is None
            assert (
                account_binding_app.SERVICE.credential_store.get_polymarket_credentials(
                    invalid_user_id
                )
                is None
            )
            assert not any(
                payload.get("user_id") == invalid_user_id
                for payload in account_binding_app.SERVICE._load_latest(
                    "binding"
                ).values()
            )

        page = client.get(f"{parsed_signing_url.path}?{parsed_signing_url.query}")
        assert page.status_code == 200
        assert page.headers["x-frame-options"] == "DENY"
        assert "frame-ancestors 'none'" in page.headers["content-security-policy"]
        assert page.headers["cache-control"] == "no-store"
        assert "Authorize your Polymarket account." in page.text
        assert "Choose wallet" in page.text
        assert "Connect Core wallet" in page.text
        assert "Authorize Polymarket" in page.text
        assert "Managed in Clink Core" in page.text
        assert wallet.address.lower() in page.text.lower()
        assert "Open Polymarket account setup" in page.text
        assert "Retry account discovery" in page.text
        assert "Connect wallet & bind Polymarket" not in page.text
        assert "Confirm deposit wallet" not in page.text
        assert "Paste your Polymarket deposit wallet" not in page.text
        assert "Authorize spending cap" not in page.text
        server_time = client.get("/polymarket/clob-server-time")
        assert server_time.status_code == 200
        assert server_time.json()["timestamp"] == "1780000000"

        signature = Account.sign_message(encode_defunct(text=session["message_to_sign"]), wallet.key).signature.hex()
        completed = client.post(
            f"/polymarket/binding-sessions/{session['session_id']}/complete",
            headers={"X-Clink-Console-Token": console_token},
            json={
                "wallet_address": wallet.address,
                "signature": signature,
                "signed_message": session["message_to_sign"],
                "clob_auth_signature": "0xclobauth",
                "clob_auth_timestamp": "1780000000",
                "clob_auth_nonce": 0,
            },
        )
        assert completed.status_code == 200
        assert completed.json()["status"] == "completed"
        legacy_binding = account_binding_app.SERVICE.get_binding(
            completed.json()["binding_id"]
        )
        assert legacy_binding is not None
        assert legacy_binding.account_mode == "eoa"
        assert legacy_binding.polymarket_signature_type == "0"
        assert legacy_binding.polymarket_deposit_wallet is None
        assert legacy_binding.wallet_address == wallet.address.lower()
        assert legacy_binding.funder_address == wallet.address.lower()

        def complete_session_with_deposit(
            *,
            user_id: str,
            session_deposit_wallet: str,
            requested_signature_type: str,
            submitted_deposit_wallet: str | None,
        ):
            created_with_deposit = client.post(
                "/internal/polymarket/binding-sessions",
                headers=internal_headers,
                json={
                    "user_id": user_id,
                    "agent_id": "hermes",
                    "polymarket_deposit_wallet": session_deposit_wallet,
                },
            )
            assert created_with_deposit.status_code == 200
            deposit_session = created_with_deposit.json()
            assert (
                deposit_session["polymarket_deposit_wallet"]
                == session_deposit_wallet.lower()
            )
            deposit_signing_url = urlparse(deposit_session["signing_url"])
            deposit_console_token = parse_qs(deposit_signing_url.query)[
                "access_token"
            ][0]
            deposit_signature = Account.sign_message(
                encode_defunct(text=deposit_session["message_to_sign"]),
                wallet.key,
            ).signature.hex()
            completed_with_deposit = client.post(
                (
                    "/polymarket/binding-sessions/"
                    f"{deposit_session['session_id']}/complete"
                ),
                headers={"X-Clink-Console-Token": deposit_console_token},
                json={
                    "wallet_address": wallet.address,
                    "signature": deposit_signature,
                    "signed_message": deposit_session["message_to_sign"],
                    "polymarket_deposit_wallet": submitted_deposit_wallet,
                    "clob_auth_signature": "0xclobauth",
                    "clob_auth_timestamp": "1780000000",
                    "clob_auth_nonce": 0,
                    "polymarket_signature_type": requested_signature_type,
                },
            )
            assert completed_with_deposit.status_code == 200
            persisted = account_binding_app.SERVICE.get_binding(
                completed_with_deposit.json()["binding_id"]
            )
            assert persisted is not None
            return persisted

        session_deposit_wallet = CHECKSUM_DEPOSIT_WALLET
        client_supplied_other_wallet = Account.create().address
        auto_binding = complete_session_with_deposit(
            user_id="api-type3-auto-user",
            session_deposit_wallet=session_deposit_wallet,
            requested_signature_type="auto",
            submitted_deposit_wallet=client_supplied_other_wallet,
        )
        assert auto_binding.account_mode == "deposit_wallet"
        assert auto_binding.polymarket_signature_type == "3"
        assert auto_binding.wallet_address == wallet.address.lower()
        assert (
            auto_binding.polymarket_deposit_wallet
            == session_deposit_wallet.lower()
        )
        assert auto_binding.funder_address == session_deposit_wallet.lower()
        assert auto_binding.metadata["deposit_wallet_source"] == "session"
        assert auto_binding.metadata["account_source"] == "session"
        assert auto_binding.metadata["requested_signature_type"] == "3"

        type_zero_deposit_wallet = Account.create().address
        type_zero_binding = complete_session_with_deposit(
            user_id="api-type3-zero-user",
            session_deposit_wallet=type_zero_deposit_wallet,
            requested_signature_type="0",
            submitted_deposit_wallet=None,
        )
        assert type_zero_binding.account_mode == "deposit_wallet"
        assert type_zero_binding.polymarket_signature_type == "3"
        assert (
            type_zero_binding.polymarket_deposit_wallet
            == type_zero_deposit_wallet.lower()
        )
        assert type_zero_binding.funder_address == type_zero_deposit_wallet.lower()
        assert type_zero_binding.metadata["deposit_wallet_source"] == "session"
        assert type_zero_binding.metadata["requested_signature_type"] == "3"

        latest = client.get("/polymarket/bindings/latest/api-user")
        assert latest.status_code == 200
        assert latest.json() == {"status": "active", "next_action": "account_binding_active"}

        internal_without_token = client.get("/internal/polymarket/bindings/latest/api-user")
        assert internal_without_token.status_code == 401
        internal_latest = client.get(
            "/internal/polymarket/bindings/latest/api-user",
            headers={"Authorization": "Bearer test-internal-token"},
        )
        assert internal_latest.status_code == 200
        assert internal_latest.json()["wallet_address"].lower() == wallet.address.lower()

        public_readiness = client.get("/clink/account/readiness?user_id=api-user")
        assert public_readiness.status_code == 200
        assert public_readiness.json()["wallet_bound"] is True
        assert "wallet_address" not in public_readiness.json()

        public_revoke = client.post("/polymarket/bindings/unknown/revoke", json={})
        assert public_revoke.status_code == 404
        control_session = client.post(
            "/internal/polymarket/binding-sessions",
            headers=internal_headers,
            json={"user_id": "api-user", "agent_id": "hermes"},
        )
        assert control_session.status_code == 200
        assert control_session.json()["binding_id"] == internal_latest.json()["binding_id"]
        control_url = urlparse(control_session.json()["signing_url"])
        control_token = parse_qs(control_url.query)["access_token"][0]
        revoke_message = (
            "Revoke Clink Polymarket Binding\n"
            f"session_id={control_session.json()['session_id']}\n"
            f"binding_id={control_session.json()['binding_id']}\n"
            "user_id=api-user\n"
            f"wallet_address={wallet.address.lower()}"
        )
        revoke_signature = Account.sign_message(
            encode_defunct(text=revoke_message), wallet.key
        ).signature.hex()
        session_revoke = client.post(
            f"/polymarket/binding-sessions/{control_session.json()['session_id']}/revoke",
            headers={"X-Clink-Console-Token": control_token},
            json={
                "wallet_address": wallet.address,
                "signature": revoke_signature,
                "signed_message": revoke_message,
            },
        )
        assert session_revoke.status_code == 200
        binding = session_revoke.json()
        assert binding["status"] == "revoked"

        print({"status": "ok", "session_id": session["session_id"], "binding_id": binding["binding_id"]})


if __name__ == "__main__":
    main()
