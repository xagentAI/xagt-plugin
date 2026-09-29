import ipaddress
import os
import socket
from urllib.parse import urlparse

import httpx
from fastapi import HTTPException


def _allow_private() -> bool:
    return os.getenv("ALLOW_PRIVATE_NETWORK", "false").lower() == "true"


BLOCKED_HOSTS = {"0.0.0.0"}
METADATA_IPS = {"169.254.169.254", "169.254.169.253", "fd00:ec2::254"}


def validate_url_for_fetch(raw_url: str) -> str:
    resolve_url_for_fetch(raw_url)
    return raw_url


def resolve_url_for_fetch(raw_url: str) -> tuple[str, ...]:
    """Validate the whole DNS answer and return numeric connection targets."""
    parsed = urlparse(raw_url)
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(status_code=400, detail="Only http/https URLs allowed")
    if parsed.username or parsed.password:
        raise HTTPException(status_code=400, detail="Credentials in URLs are not allowed")
    # Match the HTTP client's IDNA/host normalization, not a second URL parser.
    try:
        host = httpx.URL(raw_url).raw_host.decode("ascii").lower()
    except httpx.InvalidURL as exc:
        raise HTTPException(status_code=400, detail="Invalid URL") from exc
    if not host:
        raise HTTPException(status_code=400, detail="URL host missing")
    if host in BLOCKED_HOSTS:
        raise HTTPException(status_code=400, detail="Blocked host (SSRF protection)")
    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise HTTPException(status_code=400, detail="DNS resolution failed") from exc
    addresses = []
    allow_private = _allow_private()
    for info in infos:
        ip_str = info[4][0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid DNS address") from exc
        if "%" in ip_str:
            raise HTTPException(status_code=400, detail="Scoped IP addresses are not allowed")
        if not allow_private:
            effective_ip = getattr(ip, "ipv4_mapped", None) or ip
            if str(effective_ip) in METADATA_IPS:
                raise HTTPException(status_code=400, detail="Blocked cloud metadata IP")
            if (not effective_ip.is_global or effective_ip.is_multicast
                    or effective_ip.is_reserved or not ip.is_global or ip.is_reserved):
                raise HTTPException(status_code=400, detail=f"Blocked private/link-local IP: {ip_str}")
        if str(ip) not in addresses:
            addresses.append(str(ip))
    if not addresses:
        raise HTTPException(status_code=400, detail="DNS resolution returned no addresses")
    return tuple(addresses)


def is_safe_method(method: str) -> bool:
    return method.upper() in ("GET", "HEAD", "OPTIONS")
