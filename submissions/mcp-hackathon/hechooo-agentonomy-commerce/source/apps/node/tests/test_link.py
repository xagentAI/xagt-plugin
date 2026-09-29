from __future__ import annotations

import json
import unittest
from datetime import UTC, datetime, timedelta

from cryptography.exceptions import InvalidTag

from apps.node.clink_node.crypto import DeviceKeyPair
from apps.node.clink_node.link import LinkInbox, LinkMessage


class LinkRelayTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 7, 23, 8, 0, tzinfo=UTC)
        self.sender = DeviceKeyPair.generate("telegram-device")
        self.recipient = DeviceKeyPair.generate("desktop-companion")
        self.message = LinkMessage.create(
            request_id="request_123",
            sender=self.sender,
            recipient_public_key=self.recipient.public_key,
            recipient_device_id=self.recipient.device_id,
            payload={
                "kind": "wallet_approval",
                "amount": "0.10",
                "asset": "USDC",
            },
            now=self.now,
            ttl=timedelta(minutes=5),
        )

    def test_relay_envelope_contains_ciphertext_not_business_plaintext(
        self,
    ) -> None:
        encoded = self.message.to_json()

        self.assertNotIn("wallet_approval", encoded)
        self.assertNotIn("USDC", encoded)
        relay_shape = json.loads(encoded)
        self.assertIn("ciphertext", relay_shape)
        self.assertNotIn("payload", relay_shape)

    def test_recipient_can_decrypt_once(self) -> None:
        inbox = LinkInbox(self.recipient)

        payload = inbox.open(self.message, now=self.now)

        self.assertEqual(payload["amount"], "0.10")
        with self.assertRaisesRegex(ValueError, "already consumed"):
            inbox.open(self.message, now=self.now)

    def test_expired_envelope_is_rejected(self) -> None:
        inbox = LinkInbox(self.recipient)

        with self.assertRaisesRegex(ValueError, "expired"):
            inbox.open(
                self.message,
                now=self.now + timedelta(minutes=6),
            )

    def test_tampered_envelope_is_rejected(self) -> None:
        inbox = LinkInbox(self.recipient)
        tampered = self.message.tamper_ciphertext_for_test()

        with self.assertRaises(InvalidTag):
            inbox.open(tampered, now=self.now)

    def test_revoked_device_cannot_open_envelope(self) -> None:
        inbox = LinkInbox(self.recipient)
        inbox.revoke()

        with self.assertRaisesRegex(ValueError, "revoked"):
            inbox.open(self.message, now=self.now)


if __name__ == "__main__":
    unittest.main()
