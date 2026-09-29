from datetime import UTC, datetime, timedelta

import pytest

from shared.manifest import ManifestClaim, manifest_hash
from shared.models import ClinkServiceManifest, Provider, ServiceOffering


def manifest():
    return ClinkServiceManifest.model_validate(
        {
            "provider": {"name": "Risk Co", "domain": "risk.example", "source": "merchant"},
            "offerings": [{
                "name": "Wallet risk",
                "endpoint": "https://risk.example/check",
                "method": "POST",
                "payment_options": [{
                    "scheme": "exact", "network": "eip155:137",
                    "asset": "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359",
                    "amount_atomic": "10000", "pay_to": "0x" + "1" * 40,
                }],
            }],
        }
    )


def test_provider_and_offering_identity_ignore_registry_source():
    assert Provider.build_id("bazaar", "RISK.EXAMPLE") == Provider.build_id("peer", "risk.example")
    assert ServiceOffering.build_id("bazaar", "POST https://risk.example/check") == ServiceOffering.build_id("peer", "POST https://RISK.EXAMPLE/check")


def test_manifest_hash_is_deterministic_and_claim_expires():
    item = manifest()
    assert manifest_hash(item) == manifest_hash(item.model_copy(deep=True))
    now = datetime.now(UTC)
    claim = ManifestClaim(
        manifest_hash=manifest_hash(item), domain="risk.example",
        pay_to=["0x" + "1" * 40], nonce="nonce", issued_at=now,
        expires_at=now + timedelta(minutes=5),
    )
    assert claim.typed_data()["message"]["manifestHash"] == manifest_hash(item)
    with pytest.raises(ValueError, match="expired"):
        claim.model_copy(update={"expires_at": now - timedelta(seconds=1)}).assert_fresh(now)
