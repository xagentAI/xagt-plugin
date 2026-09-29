from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from clink_node.secrets import (
    EnvelopeCipher,
    MemorySecretStore,
    RestrictedFileSecretStore,
    VaultSecretStore,
)


class SecretStoreTests(unittest.TestCase):
    def test_restricted_file_store_uses_owner_only_permissions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "secrets.json"
            store = RestrictedFileSecretStore(path)
            store.set("token", b"value")

            self.assertEqual(store.get("token"), b"value")
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_restricted_file_store_rejects_world_readable_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "secrets.json"
            path.write_text("{}", encoding="utf-8")
            os.chmod(path, 0o644)

            with self.assertRaises(PermissionError):
                RestrictedFileSecretStore(path).get("token")

    def test_restricted_file_store_rejects_symlink_without_touching_target(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "target.json"
            target.write_text("{}", encoding="utf-8")
            path = root / "secrets.json"
            path.symlink_to(target)

            with self.assertRaises(PermissionError):
                RestrictedFileSecretStore(path).get("token")
            self.assertEqual(target.read_text(encoding="utf-8"), "{}")

    def test_restricted_file_store_keeps_old_document_on_replace_failure(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "secrets.json"
            store = RestrictedFileSecretStore(path)
            store.set("token", b"old")

            with patch("clink_node.secrets.os.replace", side_effect=OSError):
                with self.assertRaises(OSError):
                    store.set("token", b"new")

            self.assertEqual(store.get("token"), b"old")

    def test_envelope_cipher_uses_atomic_key_creation(self) -> None:
        class AtomicOnlyStore:
            def __init__(self) -> None:
                self.value: bytes | None = None

            def get(self, name: str) -> bytes | None:
                del name
                return self.value

            def set(self, name: str, value: bytes) -> None:
                del name, value
                raise AssertionError("non-atomic key write")

            def set_if_absent(self, name: str, value: bytes) -> bool:
                del name
                if self.value is not None:
                    return False
                self.value = bytes(value)
                return True

            def delete(self, name: str) -> None:
                del name

        store = AtomicOnlyStore()
        cipher = EnvelopeCipher(store)
        encrypted = cipher.encrypt(b"payload", purpose="test")
        self.assertEqual(cipher.decrypt(encrypted, purpose="test"), b"payload")
        self.assertEqual(len(store.value or b""), 32)

    def test_envelope_encryption_binds_ciphertext_to_purpose(self) -> None:
        store = MemorySecretStore({})
        cipher = EnvelopeCipher(store)
        ciphertext = cipher.encrypt(
            b'{"wallet":"0x123"}',
            purpose="account-binding",
        )

        self.assertNotIn("0x123", ciphertext)
        self.assertEqual(
            cipher.decrypt(ciphertext, purpose="account-binding"),
            b'{"wallet":"0x123"}',
        )
        with self.assertRaises(Exception):
            cipher.decrypt(ciphertext, purpose="other-purpose")

    @patch("clink_node.secrets.urlopen")
    def test_vault_store_uses_kv_v2_and_never_logs_plaintext(
        self,
        mocked_urlopen,
    ) -> None:
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def read(self) -> bytes:
                return (
                    b'{"data":{"data":{"value":"c2VjcmV0"}}}'
                )

        mocked_urlopen.return_value = Response()
        store = VaultSecretStore(
            "https://vault.example",
            token="vault-token",
            mount="secret",
            path_prefix="clink/prod",
        )

        self.assertEqual(store.get("node-envelope-key-v1"), b"secret")

        request = mocked_urlopen.call_args.args[0]
        self.assertEqual(
            request.full_url,
            "https://vault.example/v1/secret/data/clink/prod/"
            "node-envelope-key-v1",
        )
        self.assertEqual(request.headers["X-vault-token"], "vault-token")

    def test_vault_rejects_public_http_but_allows_explicit_loopback_http(
        self,
    ) -> None:
        with self.assertRaises(ValueError):
            VaultSecretStore("http://vault.example", token="vault-token")
        self.assertIsNotNone(
            VaultSecretStore(
                "http://127.0.0.1:8200",
                token="vault-token",
            )
        )

    @patch("clink_node.secrets.urlopen")
    def test_vault_store_writes_base64_encoded_values(
        self,
        mocked_urlopen,
    ) -> None:
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def read(self) -> bytes:
                return b"{}"

        mocked_urlopen.return_value = Response()
        store = VaultSecretStore(
            "https://vault.example/",
            token="vault-token",
        )

        store.set("core-token", b"sensitive")

        request = mocked_urlopen.call_args.args[0]
        self.assertEqual(request.method, "POST")
        self.assertEqual(
            request.full_url,
            "https://vault.example/v1/secret/data/clink/core-token",
        )
        self.assertEqual(
            request.data,
            b'{"data":{"value":"c2Vuc2l0aXZl"}}',
        )


if __name__ == "__main__":
    unittest.main()
