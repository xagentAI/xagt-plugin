from __future__ import annotations

import pytest

from kms_signer import KMSConfigurationError, KMSSigningError, KMSExecutionSigner


DIGEST = bytes.fromhex("6ea762e95a41acc79914afb2c7500d456006df9c6b848d4d6a9c71a60e282055")
PUBLIC_KEY_DER = bytes.fromhex(
    "3056301006072a8648ce3d020106052b8104000a03420004"
    "79be667ef9dcbbac55a06295ce870b07029bfcdb2dce28d959f2815b16f81798"
    "483ada7726a3c4655da4fbfc0e1108a8fd17b448a68554199c47d08ffb10d4b8"
)
SIGNER_ADDRESS = "0x7E5F4552091A69125d5DfCb7b8C2659029395Bdf"
OTHER_ADDRESS = "0x2B5AD5c4795c026514f8317c7a215E218DcCD6cF"
LOW_DER = bytes.fromhex(
    "3045022100e6ab41d4f7e9f420598d57820c4b87074cff9ed21f14a68b5214fd653046b762"
    "0220290168e92e94dfa7e5fb33bc0355ea71fed0e2c4a07f3fcf62be0aede56298d1"
)
HIGH_DER = bytes.fromhex(
    "3046022100e6ab41d4f7e9f420598d57820c4b87074cff9ed21f14a68b5214fd653046b762"
    "022100d6fe9716d16b20581a04cc43fcaa158cbbddfa220ec9606c5d14539eead3a870"
)
LOW_COMPACT = bytes.fromhex(
    "e6ab41d4f7e9f420598d57820c4b87074cff9ed21f14a68b5214fd653046b762"
    "290168e92e94dfa7e5fb33bc0355ea71fed0e2c4a07f3fcf62be0aede56298d1"
    "1b"
)


class FakeKMS:
    def __init__(self, *, signature: bytes = LOW_DER, **metadata: object) -> None:
        self.signature = signature
        self.metadata = {
            "KeySpec": "ECC_SECG_P256K1",
            "KeyUsage": "SIGN_VERIFY",
            **metadata,
        }
        self.public_key_calls: list[dict[str, object]] = []
        self.sign_calls: list[dict[str, object]] = []

    def get_public_key(self, **kwargs: object) -> dict[str, object]:
        self.public_key_calls.append(kwargs)
        return {**self.metadata, "PublicKey": PUBLIC_KEY_DER}

    def sign(self, **kwargs: object) -> dict[str, object]:
        self.sign_calls.append(kwargs)
        return {"Signature": self.signature}


def signer(client: FakeKMS, **kwargs: object) -> KMSExecutionSigner:
    return KMSExecutionSigner(
        client,
        key_id="arn:aws:kms:us-east-1:123456789012:key/execution",
        expected_signer_address=SIGNER_ADDRESS,
        **kwargs,
    )


def test_kms_signer_uses_exact_key_spec_and_sign_parameters() -> None:
    client = FakeKMS()

    signature = signer(client).sign_digest(DIGEST)

    assert signature == LOW_COMPACT
    assert client.public_key_calls == [
        {"KeyId": "arn:aws:kms:us-east-1:123456789012:key/execution"}
    ]
    assert client.sign_calls == [
        {
            "KeyId": "arn:aws:kms:us-east-1:123456789012:key/execution",
            "Message": DIGEST,
            "MessageType": "DIGEST",
            "SigningAlgorithm": "ECDSA_SHA_256",
        }
    ]


def test_kms_high_s_der_is_normalized_and_recovery_parity_is_recovered() -> None:
    signature = signer(FakeKMS(signature=HIGH_DER)).sign_digest(DIGEST)

    assert signature == LOW_COMPACT
    assert signature[-1] == 27


@pytest.mark.parametrize(
    "metadata",
    [
        {"KeySpec": "ECC_NIST_P256"},
        {"KeyUsage": "ENCRYPT_DECRYPT"},
    ],
)
def test_kms_rejects_wrong_key_spec_or_usage(metadata: dict[str, str]) -> None:
    with pytest.raises(KMSSigningError, match="KMS key is not an ECDSA signing key"):
        signer(FakeKMS(**metadata)).sign_digest(DIGEST)


def test_kms_rejects_wrong_expected_signer_without_returning_signature() -> None:
    client = FakeKMS()
    wrong = KMSExecutionSigner(
        client,
        key_id="execution-key",
        expected_signer_address=OTHER_ADDRESS,
    )

    with pytest.raises(KMSSigningError, match="signer address mismatch"):
        wrong.sign_digest(DIGEST)
    assert client.sign_calls == []


def test_kms_rejects_digest_and_configuration_boundaries() -> None:
    with pytest.raises(KMSSigningError, match="digest must be exactly 32 bytes"):
        signer(FakeKMS()).sign_digest(b"short")
    with pytest.raises(KMSConfigurationError, match="execution and gas signer keys must differ"):
        signer(FakeKMS(), gas_relayer_key_id="arn:aws:kms:us-east-1:123456789012:key/execution")
    with pytest.raises(KMSConfigurationError, match="execution and gas signer addresses must differ"):
        signer(FakeKMS(), gas_relayer_address=SIGNER_ADDRESS)


def test_kms_validate_checks_public_identity_without_signing() -> None:
    client = FakeKMS()

    assert signer(client).validate() is None
    assert client.sign_calls == []
    assert client.public_key_calls == [
        {"KeyId": "arn:aws:kms:us-east-1:123456789012:key/execution"}
    ]


def test_kms_repr_does_not_include_public_key_or_signature_material() -> None:
    representation = repr(signer(FakeKMS()))

    assert "arn:aws:kms:us-east-1:123456789012:key/execution" not in representation
    assert "key_ref='<redacted>'" in representation
    assert PUBLIC_KEY_DER.hex() not in representation
    assert LOW_DER.hex() not in representation
