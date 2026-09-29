from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from adapters.cdp_bazaar import CdpBazaarAdapter
from shared.config import AppConfig


def main() -> None:
    config = AppConfig.from_env()
    adapter = CdpBazaarAdapter(search_url=config.bazaar_search_url)
    resources = adapter.search("API", limit=1)
    if not resources:
        raise AssertionError("CDP Bazaar returned no resources for compatibility smoke")
    provider, offering = adapter.normalize_resource(resources[0])
    if not offering.payment_options:
        raise AssertionError("CDP Bazaar resource has no normalized payment options")
    payment = offering.payment_options[0]
    print(
        json.dumps(
            {
                "status": "ok",
                "provider": provider.domain,
                "offering_id": offering.offering_id,
                "network": payment.network,
                "price_usd": str(payment.price_usd) if payment.price_usd is not None else None,
                "pay_to_present": bool(payment.pay_to),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
