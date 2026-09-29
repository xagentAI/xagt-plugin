import json
import sys
import tempfile
from pathlib import Path

from cryptography.fernet import Fernet

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from services.account_binding_service.credential_store import CredentialStore, PolymarketApiCredentials  # noqa: E402
from shared.config import AppConfig  # noqa: E402


def main() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        config = AppConfig(
            account_binding_file=str(Path(tmpdir) / "bindings.jsonl"),
            credential_store_file=str(Path(tmpdir) / "credentials.jsonl"),
            credential_encryption_key=Fernet.generate_key().decode("utf-8"),
        )
        store = CredentialStore(config)
        credentials = PolymarketApiCredentials(
            api_key="pm-key",
            api_secret="pm-secret",
            api_passphrase="pm-passphrase",
            signature_type="3",
            funder_address="0x1111111111111111111111111111111111111111",
        )
        record = store.save_polymarket_credentials(
            user_id="telegram_demo_user",
            wallet_address="0x2222222222222222222222222222222222222222",
            credentials=credentials,
        )

        raw_storage = Path(config.credential_store_file).read_text()
        assert "pm-secret" not in raw_storage
        assert "pm-passphrase" not in raw_storage
        assert record.api_key_fingerprint.startswith("sha256:")

        loaded = store.get_polymarket_credentials("telegram_demo_user")
        assert loaded is not None
        assert loaded.api_key == "pm-key"
        assert loaded.api_secret == "pm-secret"
        assert loaded.api_passphrase == "pm-passphrase"
        assert loaded.funder_address == "0x1111111111111111111111111111111111111111"

        missing = store.get_polymarket_credentials("unknown-user")
        assert missing is None

        print(json.dumps({"status": "ok", "fingerprint": record.api_key_fingerprint}, indent=2))


if __name__ == "__main__":
    main()
