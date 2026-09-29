from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from services.deposit_wallet_service.schemas import PreparePolymarketDepositWalletRequest
from services.deposit_wallet_service.service import PolymarketDepositWalletService
from shared.config import AppConfig


def write_state(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


class FakeRelayerClient:
    def __init__(self) -> None:
        self.deployed = False
        self.deploy_calls = 0
        self.deployment_checks: list[str] = []

    def derive_deposit_wallet(self, owner_wallet: str) -> dict:
        return {
            "deposit_wallet": "0x2222222222222222222222222222222222222222",
            "owner_wallet": owner_wallet,
            "source": "fake_builder_relayer",
        }

    def deploy_deposit_wallet(self, owner_wallet: str) -> dict:
        self.deploy_calls += 1
        self.deployed = True
        return {
            "deposit_wallet": "0x2222222222222222222222222222222222222222",
            "owner_wallet": owner_wallet,
            "transaction_id": "relayer_tx_123",
            "state": "STATE_NEW",
            "source": "fake_builder_relayer",
        }

    def is_deposit_wallet_deployed(self, deposit_wallet: str) -> bool:
        self.deployment_checks.append(deposit_wallet)
        return self.deployed


class DeploymentCheckErrorRelayerClient(FakeRelayerClient):
    def is_deposit_wallet_deployed(self, deposit_wallet: str) -> bool:
        raise RuntimeError("sensitive upstream detail")


class SubmittedOnlyRelayerClient:
    def derive_deposit_wallet(self, owner_wallet: str) -> dict:
        return {
            "deposit_wallet": "0x3333333333333333333333333333333333333333",
            "owner_wallet": owner_wallet,
            "source": "fake_builder_relayer",
        }

    def deploy_deposit_wallet(self, owner_wallet: str) -> dict:
        return {
            "transactionID": "relayer_tx_submitted",
            "transactionHash": "0xabc",
            "state": "STATE_NEW",
            "source": "fake_builder_relayer",
        }


class ConfirmedSubmittedRelayerClient(SubmittedOnlyRelayerClient):
    def get_transaction(self, transaction_id: str) -> dict:
        return {
            "transactionID": transaction_id,
            "transactionHash": "0xconfirmed",
            "state": "STATE_CONFIRMED",
        }

    def is_deposit_wallet_deployed(self, deposit_wallet: str) -> bool:
        return True


def main() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        missing_config = AppConfig(
            deposit_wallet_state_file=str(Path(tmpdir) / "missing.jsonl"),
            polymarket_relayer_url="",
            polymarket_builder_api_key="",
            polymarket_builder_secret="",
            polymarket_builder_passphrase="",
        )
        missing_service = PolymarketDepositWalletService(config=missing_config)
        missing = missing_service.check_readiness(
            user_id="telegram_demo_user",
            owner_wallet="0x1111111111111111111111111111111111111111",
        )
        assert missing.status == "credentials_missing"
        assert missing.ready is False
        assert "POLYMARKET_RELAYER_URL" in missing.missing
        assert missing.next_action == "configure_builder_relayer"

        ready_config = AppConfig(
            deposit_wallet_state_file=str(Path(tmpdir) / "ready.jsonl"),
            polymarket_relayer_url="https://relayer-v2.polymarket.com",
            polymarket_builder_api_key="builder_key",
            polymarket_builder_secret="builder_secret",
            polymarket_builder_passphrase="builder_passphrase",
        )
        service = PolymarketDepositWalletService(config=ready_config, relayer_client=FakeRelayerClient())
        derived = service.prepare_deposit_wallet(
            PreparePolymarketDepositWalletRequest(
                user_id="telegram_demo_user",
                owner_wallet="0x1111111111111111111111111111111111111111",
                mode="derive",
            )
        )
        assert derived.status == "derived"
        assert derived.deposit_wallet == "0x2222222222222222222222222222222222222222"
        assert derived.next_action == "deploy_polymarket_deposit_wallet"

        readiness = service.check_readiness(
            user_id="telegram_demo_user",
            owner_wallet="0x1111111111111111111111111111111111111111",
        )
        assert readiness.status == "derived"
        assert readiness.ready is False
        assert readiness.can_use_x402 is False
        assert readiness.next_action == "deploy_polymarket_deposit_wallet"
        assert readiness.deposit_wallet == "0x2222222222222222222222222222222222222222"

        service.relayer_client.deployed = True
        reconciled = service.check_readiness(
            user_id="telegram_demo_user",
            owner_wallet="0x1111111111111111111111111111111111111111",
        )
        assert reconciled.status == "deployed"
        assert reconciled.ready is True
        assert reconciled.can_use_x402 is True
        assert reconciled.next_action == "fund_polymarket_deposit_wallet"
        assert reconciled.state is not None
        assert reconciled.state.metadata["deposit_wallet_deployed_by_chain_code"] is True
        assert service.relayer_client.deploy_calls == 0

        migrated_subject = service.check_readiness(
            user_id="telegram:123456789",
            owner_wallet="0x1111111111111111111111111111111111111111",
        )
        assert migrated_subject.user_id == "telegram:123456789"
        assert migrated_subject.owner_wallet == "0x1111111111111111111111111111111111111111"
        assert migrated_subject.deposit_wallet == "0x2222222222222222222222222222222222222222"
        assert migrated_subject.status == "deployed"
        assert migrated_subject.ready is True
        assert migrated_subject.can_use_x402 is True

        restarted = PolymarketDepositWalletService(
            config=ready_config,
            relayer_client=FakeRelayerClient(),
        )
        persisted = restarted.check_readiness(
            user_id="telegram_demo_user",
            owner_wallet="0x1111111111111111111111111111111111111111",
        )
        assert persisted.status == "deployed"
        assert persisted.ready is True

        error_config = AppConfig(
            deposit_wallet_state_file=str(Path(tmpdir) / "derived-error.jsonl"),
            polymarket_relayer_url="https://relayer-v2.polymarket.com",
            polymarket_builder_api_key="builder_key",
            polymarket_builder_secret="builder_secret",
            polymarket_builder_passphrase="builder_passphrase",
        )
        error_service = PolymarketDepositWalletService(
            config=error_config,
            relayer_client=DeploymentCheckErrorRelayerClient(),
        )
        error_service.prepare_deposit_wallet(
            PreparePolymarketDepositWalletRequest(
                user_id="telegram_demo_user",
                owner_wallet="0x1111111111111111111111111111111111111111",
                mode="derive",
            )
        )
        failed_closed = error_service.check_readiness(
            user_id="telegram_demo_user",
            owner_wallet="0x1111111111111111111111111111111111111111",
        )
        assert failed_closed.status == "derived"
        assert failed_closed.ready is False
        assert failed_closed.can_use_x402 is False
        assert failed_closed.state is not None
        assert failed_closed.state.metadata["derived_deployment_check_error"] == "RuntimeError"
        assert "sensitive upstream detail" not in json.dumps(failed_closed.model_dump())

        error_restarted = PolymarketDepositWalletService(
            config=error_config,
            relayer_client=FakeRelayerClient(),
        )
        persisted_error = error_restarted.check_readiness(
            user_id="telegram_demo_user",
            owner_wallet="0x1111111111111111111111111111111111111111",
        )
        assert persisted_error.status == "derived"
        assert persisted_error.state is not None
        assert "derived_deployment_check_error" not in persisted_error.state.metadata

        owner_scoped_config = AppConfig(
            deposit_wallet_state_file=str(Path(tmpdir) / "owner-scoped.jsonl"),
            polymarket_relayer_url="https://relayer-v2.polymarket.com",
            polymarket_builder_api_key="builder_key",
            polymarket_builder_secret="builder_secret",
            polymarket_builder_passphrase="builder_passphrase",
        )
        owner_scoped_relayer = FakeRelayerClient()
        owner_scoped_service = PolymarketDepositWalletService(
            config=owner_scoped_config,
            relayer_client=owner_scoped_relayer,
        )
        owner_scoped_service.prepare_deposit_wallet(
            PreparePolymarketDepositWalletRequest(
                user_id="telegram_rebound_user",
                owner_wallet="0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                mode="derive",
            )
        )
        owner_scoped_relayer.deployed = True
        owner_b_readiness = owner_scoped_service.check_readiness(
            user_id="telegram_rebound_user",
            owner_wallet="0xbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        )
        assert owner_b_readiness.status == "not_prepared"
        assert owner_b_readiness.owner_wallet == "0xbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
        assert owner_b_readiness.deposit_wallet is None
        assert owner_b_readiness.state is None
        assert owner_b_readiness.ready is False
        assert owner_b_readiness.can_use_x402 is False
        assert owner_b_readiness.next_action == "prepare_polymarket_deposit_wallet"
        assert owner_scoped_relayer.deployment_checks == []

        deployed = service.prepare_deposit_wallet(
            PreparePolymarketDepositWalletRequest(
                user_id="telegram_demo_user",
                owner_wallet="0x1111111111111111111111111111111111111111",
                mode="deploy",
            )
        )
        assert deployed.status == "deployed"
        assert deployed.next_action == "fund_polymarket_deposit_wallet"

        submitted_config = AppConfig(
            deposit_wallet_state_file=str(Path(tmpdir) / "submitted.jsonl"),
            polymarket_relayer_url="https://relayer-v2.polymarket.com",
            polymarket_builder_api_key="builder_key",
            polymarket_builder_secret="builder_secret",
            polymarket_builder_passphrase="builder_passphrase",
        )
        submitted_service = PolymarketDepositWalletService(
            config=submitted_config,
            relayer_client=SubmittedOnlyRelayerClient(),
        )
        submitted_service.prepare_deposit_wallet(
            PreparePolymarketDepositWalletRequest(
                user_id="telegram_demo_user",
                owner_wallet="0x1111111111111111111111111111111111111111",
                mode="derive",
            )
        )
        submitted = submitted_service.prepare_deposit_wallet(
            PreparePolymarketDepositWalletRequest(
                user_id="telegram_demo_user",
                owner_wallet="0x1111111111111111111111111111111111111111",
                mode="deploy",
            )
        )
        assert submitted.status == "submitted"
        assert submitted.deposit_wallet == "0x3333333333333333333333333333333333333333"
        assert submitted.transaction_id == "relayer_tx_submitted"
        assert submitted.relayer_state == "STATE_NEW"
        assert submitted.next_action == "poll_polymarket_relayer_transaction"
        assert submitted.can_use_x402 is False

        submitted_readiness = submitted_service.check_readiness(
            user_id="telegram_demo_user",
            owner_wallet="0x1111111111111111111111111111111111111111",
        )
        assert submitted_readiness.status == "submitted"
        assert submitted_readiness.deposit_wallet == "0x3333333333333333333333333333333333333333"
        assert submitted_readiness.ready is False
        assert submitted_readiness.can_use_x402 is False
        assert submitted_readiness.next_action == "poll_polymarket_relayer_transaction"

        legacy_state_file = Path(tmpdir) / "legacy-submitted.jsonl"
        write_state(
            legacy_state_file,
            {
                "user_id": "telegram_demo_user",
                "owner_wallet": "0x1111111111111111111111111111111111111111",
                "deposit_wallet": "0x4444444444444444444444444444444444444444",
                "status": "derived",
                "reason": None,
                "next_action": "deploy_polymarket_deposit_wallet",
                "can_use_x402": True,
                "transaction_id": None,
                "relayer_state": None,
                "created_at": "2026-07-06T00:00:00Z",
                "updated_at": "2026-07-06T00:00:00Z",
                "raw_response": {},
                "metadata": {},
            },
        )
        write_state(
            legacy_state_file,
            {
                "user_id": "telegram_demo_user",
                "owner_wallet": "0x1111111111111111111111111111111111111111",
                "deposit_wallet": None,
                "status": "submitted",
                "reason": "relayer accepted deployment but deposit wallet address was not returned yet",
                "next_action": "poll_polymarket_relayer_transaction",
                "can_use_x402": False,
                "transaction_id": "relayer_tx_legacy",
                "relayer_state": "STATE_NEW",
                "created_at": "2026-07-06T00:01:00Z",
                "updated_at": "2026-07-06T00:01:00Z",
                "raw_response": {"transactionID": "relayer_tx_legacy", "state": "STATE_NEW"},
                "metadata": {},
            },
        )
        legacy_service = PolymarketDepositWalletService(
            config=AppConfig(
                deposit_wallet_state_file=str(legacy_state_file),
                polymarket_relayer_url="https://relayer-v2.polymarket.com",
                polymarket_builder_api_key="builder_key",
                polymarket_builder_secret="builder_secret",
                polymarket_builder_passphrase="builder_passphrase",
            ),
            relayer_client=SubmittedOnlyRelayerClient(),
        )
        legacy_readiness = legacy_service.check_readiness(
            user_id="telegram_demo_user",
            owner_wallet="0x1111111111111111111111111111111111111111",
        )
        assert legacy_readiness.status == "submitted"
        assert legacy_readiness.deposit_wallet == "0x4444444444444444444444444444444444444444"
        assert legacy_readiness.state is not None
        assert legacy_readiness.state.deposit_wallet == "0x4444444444444444444444444444444444444444"
        assert legacy_readiness.state.transaction_id == "relayer_tx_legacy"
        assert legacy_readiness.can_use_x402 is False

        confirmed_state_file = Path(tmpdir) / "confirmed-submitted.jsonl"
        write_state(
            confirmed_state_file,
            {
                "user_id": "telegram_demo_user",
                "owner_wallet": "0x1111111111111111111111111111111111111111",
                "deposit_wallet": "0x5555555555555555555555555555555555555555",
                "status": "submitted",
                "reason": "relayer accepted deployment but deposit wallet address was not returned yet",
                "next_action": "poll_polymarket_relayer_transaction",
                "can_use_x402": False,
                "transaction_id": "relayer_tx_confirmed",
                "relayer_state": "STATE_NEW",
                "created_at": "2026-07-06T00:02:00Z",
                "updated_at": "2026-07-06T00:02:00Z",
                "raw_response": {"transactionID": "relayer_tx_confirmed", "state": "STATE_NEW"},
                "metadata": {},
            },
        )
        confirmed_service = PolymarketDepositWalletService(
            config=AppConfig(
                deposit_wallet_state_file=str(confirmed_state_file),
                polymarket_relayer_url="https://relayer-v2.polymarket.com",
                polymarket_builder_api_key="builder_key",
                polymarket_builder_secret="builder_secret",
                polymarket_builder_passphrase="builder_passphrase",
            ),
            relayer_client=ConfirmedSubmittedRelayerClient(),
        )
        confirmed_readiness = confirmed_service.check_readiness(
            user_id="telegram_demo_user",
            owner_wallet="0x1111111111111111111111111111111111111111",
        )
        assert confirmed_readiness.status == "deployed"
        assert confirmed_readiness.deposit_wallet == "0x5555555555555555555555555555555555555555"
        assert confirmed_readiness.ready is True
        assert confirmed_readiness.can_use_x402 is True
        assert confirmed_readiness.next_action == "fund_polymarket_deposit_wallet"
        assert confirmed_readiness.state is not None
        assert confirmed_readiness.state.relayer_state == "STATE_CONFIRMED"
        assert confirmed_readiness.state.raw_response["transactionHash"] == "0xconfirmed"

    print(json.dumps({"status": "ok"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
