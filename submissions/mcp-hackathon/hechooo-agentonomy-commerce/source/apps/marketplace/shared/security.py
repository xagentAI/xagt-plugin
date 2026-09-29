from __future__ import annotations

import ipaddress
from urllib.parse import urlsplit


def validate_public_https_url(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.scheme.lower() != "https":
        raise ValueError("service endpoint must use https")
    if not parsed.hostname:
        raise ValueError("service endpoint must include a hostname")
    if parsed.username or parsed.password:
        raise ValueError("service endpoint must not contain credentials")

    hostname = parsed.hostname.lower().rstrip(".")
    if hostname == "localhost" or hostname.endswith((".localhost", ".local")):
        raise ValueError("local service endpoints are not allowed")

    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        return url

    if not address.is_global:
        raise ValueError("private or non-global service endpoints are not allowed")
    return url


def payment_recipient_matches(network: str, actual: str, expected: str) -> bool:
    if network.lower().startswith("eip155:"):
        return actual.lower() == expected.lower()
    return actual == expected
