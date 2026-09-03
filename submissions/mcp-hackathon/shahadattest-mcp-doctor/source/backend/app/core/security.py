import ipaddress
import os
import socket
from urllib.parse import urlparse

from fastapi import HTTPException


def _allow_private() -> bool:
    return os.getenv("ALLOW_PRIVATE_NETWORK", "false").lower() == "true"


BLOCKED_HOSTS = {"0.0.0.0"}
DEV_HOSTS = {"localhost", "127.0.0.1", "::1"}
METADATA_IPS = {"169.254.169.254", "169.254.169.253", "fd00:ec2::254"}


def validate_url_for_fetch(raw_url: str) -> str:
    try:
        parsed = urlparse(raw_url)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid URL")
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(status_code=400, detail="Only http/https URLs allowed")
    host = (parsed.hostname or "").lower()
    if not host:
        raise HTTPException(status_code=400, detail="URL host missing")
    if host in BLOCKED_HOSTS:
        raise HTTPException(status_code=400, detail="Blocked host (SSRF protection)")
    if host in DEV_HOSTS and _allow_private():
        return raw_url
    if not _allow_private():
        try:
            infos = socket.getaddrinfo(host, None)
        except socket.gaierror:
            raise HTTPException(status_code=400, detail="DNS resolution failed")
        for info in infos:
            ip_str = info[4][0]
            if ip_str in METADATA_IPS:
                raise HTTPException(status_code=400, detail="Blocked cloud metadata IP")
            try:
                ip = ipaddress.ip_address(ip_str)
            except ValueError:
                continue
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified:
                raise HTTPException(status_code=400, detail=f"Blocked private/link-local IP: {ip_str}")
    return raw_url


def is_safe_method(method: str) -> bool:
    return method.upper() in ("GET", "HEAD", "OPTIONS")
