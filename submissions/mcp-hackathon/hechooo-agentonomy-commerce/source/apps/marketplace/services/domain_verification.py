from __future__ import annotations
import ipaddress, socket
from urllib.parse import urlsplit
import httpx

class DomainVerifier:
    def __init__(self, client=None, resolver=None): self.client=client or httpx.Client(timeout=10,follow_redirects=False);self.resolver=resolver or socket.gethostbyname_ex
    def verify(self, *, domain, provider_id, wallet_address):
        host=domain.lower().rstrip(".")
        addresses=self.resolver(host)[2]
        if not addresses or any(ipaddress.ip_address(ip).is_private or ipaddress.ip_address(ip).is_loopback or ipaddress.ip_address(ip).is_link_local for ip in addresses): raise ValueError("domain resolves to a non-public address")
        url=f"https://{host}/.well-known/clink-verification.json"
        response=self.client.get(url,headers={"Accept":"application/json"});response.raise_for_status()
        if urlsplit(str(response.url)).hostname!=host: raise ValueError("domain verification redirect is forbidden")
        payload=response.json()
        if payload.get("provider_id")!=provider_id or payload.get("wallet_address","").lower()!=wallet_address.lower(): raise ValueError("domain verification claim mismatch")
        return payload
