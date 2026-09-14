"""Local protocol client for the paid qualification route.

Default mode is mock and never signs or broadcasts anything. The real Hedera
client is provided in consume.mjs; it uses @x402/hedera after explicit approval.
"""

from __future__ import annotations

import base64
import json
import os
import sys
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def main() -> int:
    service = os.getenv("SERVICE_URL", "http://127.0.0.1:8787/v1/paid/qualify")
    site_path = sys.argv[1] if len(sys.argv) > 1 else "examples/site-ready.json"
    site = json.load(open(site_path, encoding="utf-8"))
    request = Request(service, data=json.dumps(site).encode(), headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urlopen(request, timeout=10) as response:
            if response.status != 402:
                print(response.read().decode())
                return 0
            required = json.loads(response.read().decode())
    except HTTPError as response:
        if response.code != 402:
            raise
        required = json.loads(response.read().decode())

    mode = os.getenv("X402_MODE", "mock")
    if mode == "mock":
        accepted = required["accepts"][0]
        payload = {"x402Version": 2, "scheme": "exact", "network": accepted["network"], "accepted": accepted, "payload": {"mock": "local-test-only"}}
        payment_header = base64.b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode()
    else:
        payment_header = os.getenv("X402_SIGNED_PAYMENT_PAYLOAD_B64", "")
        if not payment_header:
            raise RuntimeError("real mode requires a signed testnet payment payload")
    retry = Request(service, data=json.dumps(site).encode(), headers={"Content-Type": "application/json", "PAYMENT-SIGNATURE": payment_header}, method="POST")
    with urlopen(retry, timeout=10) as response:
        print(response.read().decode())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
