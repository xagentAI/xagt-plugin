from types import SimpleNamespace

import pytest

from services.purchase_service import PurchaseService


NETWORK = "eip155:137"
TOKEN = "0x" + "11" * 20
EXECUTOR = "0x" + "22" * 20
BASE_NETWORK = "eip155:8453"
BASE_TOKEN = "0x" + "44" * 20
BASE_EXECUTOR = "0x" + "55" * 20


class HostedCore:
    def __init__(self, readiness):
        self.readiness = readiness
        self.authorization_payload = None

    def funding_readiness(self):
        return self.readiness

    def resolve_authorization(self, payload):
        self.authorization_payload = payload
        return {"ready": True, **payload}


def _readiness(**overrides):
    value = {
        "status": "ready",
        "settlement_rail": "clink_hosted_executor",
        "live_funding_enabled": True,
        "hosted_facilitator_enabled": True,
        "hosted_facilitator_ready": True,
        "automatic_payment_rail": "clink_hosted_executor",
        "supported_assets": {NETWORK: TOKEN},
        "spender_address": None,
        "spender_addresses": {NETWORK: EXECUTOR},
    }
    value.update(overrides)
    return value


def _resolve(core, *, asset=TOKEN, network=NETWORK):
    service = PurchaseService(repository=None, core=core)
    return service._resolve_authorization_fields(
        user_id="user_1",
        execution_mode="clink_allowance",
        offering=SimpleNamespace(
            provider_id="provider_1",
            endpoint="https://merchant.example/service",
            metadata={"trust_tier": "clink_verified"},
        ),
        payment={
            "network": network,
            "asset": asset,
            "price_usd": "1.00",
            "pay_to": "0x" + "33" * 20,
        },
    )


@pytest.mark.parametrize(
    "network,token,executor",
    [
        (NETWORK, TOKEN, EXECUTOR),
        (BASE_NETWORK, BASE_TOKEN, BASE_EXECUTOR),
    ],
)
def test_allowance_purchase_uses_the_signed_executor_for_its_network(
    network, token, executor
):
    core = HostedCore(
        _readiness(
            supported_assets={network: token},
            spender_addresses={network: executor},
        )
    )

    authorization = _resolve(core, network=network, asset=token)

    assert authorization["ready"] is True
    assert core.authorization_payload["authorization_rail"] == "native_allowance"
    assert core.authorization_payload["spender_address"] == executor


@pytest.mark.parametrize(
    "readiness",
    [
        _readiness(status="not_ready"),
        _readiness(hosted_facilitator_enabled=False),
        _readiness(hosted_facilitator_ready=False),
        _readiness(settlement_rail="clink_native_facilitator"),
    ],
)
def test_allowance_purchase_rejects_an_unready_hosted_executor(readiness):
    with pytest.raises(ValueError, match="Hosted executor is not ready"):
        _resolve(HostedCore(readiness))


def test_allowance_purchase_rejects_a_hosted_asset_mismatch():
    with pytest.raises(ValueError, match="network and asset"):
        _resolve(HostedCore(_readiness()), asset="0x" + "44" * 20)


def test_allowance_purchase_rejects_a_missing_network_executor():
    readiness = _readiness(spender_addresses={"eip155:8453": EXECUTOR})

    with pytest.raises(ValueError, match="network and asset"):
        _resolve(HostedCore(readiness))
