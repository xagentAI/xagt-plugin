"""Fixed first-party service routing over real HTTP, never a general URL proxy."""
from urllib.parse import urlsplit

import httpx


class LoopbackMerchantTransport(httpx.BaseTransport):
    def __init__(self, resource: str, endpoint: str):
        parsed = urlsplit(endpoint)
        if (parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or
                parsed.username or parsed.password or parsed.query or parsed.fragment or
                parsed.path != "/v1/reconcile" or parsed.port is None):
            raise ValueError("merchant transport requires the fixed loopback service")
        self.resource = resource
        self.endpoint = endpoint
        self.inner = httpx.HTTPTransport(retries=0, trust_env=False)

    def handle_request(self, request):
        if str(request.url) != self.resource or request.method != "POST":
            raise ValueError("unconfigured merchant resource")
        headers = dict(request.headers)
        headers["host"] = urlsplit(self.endpoint).netloc
        routed = httpx.Request(request.method, self.endpoint, headers=headers,
                               content=request.read(), extensions=request.extensions)
        return self.inner.handle_request(routed)

    def close(self):
        self.inner.close()
