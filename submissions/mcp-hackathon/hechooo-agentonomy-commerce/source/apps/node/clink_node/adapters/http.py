from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx


@dataclass(frozen=True)
class ProxyResponse:
    status_code: int
    content: bytes
    headers: tuple[tuple[str, str], ...]

    def header_values(self, name: str) -> list[str]:
        expected = name.lower()
        return [
            value
            for key, value in self.headers
            if key.lower() == expected
        ]


class DownstreamError(RuntimeError):
    def __init__(
        self,
        service: str,
        status_code: int | None,
        detail: str,
    ) -> None:
        self.service = service
        self.status_code = status_code
        self.detail = detail
        super().__init__(
            f"{service} request failed"
            + (f" with HTTP {status_code}" if status_code else "")
            + f": {detail}"
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "error": "downstream_unavailable",
            "service": self.service,
            "status_code": self.status_code,
            "detail": self.detail,
            "retry_safe": False,
        }


class JsonHttpClient:
    def __init__(
        self,
        service: str,
        *,
        internal_token: str = "",
        timeout_seconds: float = 10,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.service = service
        headers = {"Accept": "application/json"}
        if internal_token:
            headers["Authorization"] = f"Bearer {internal_token}"
        self.client = httpx.Client(
            headers=headers,
            timeout=timeout_seconds,
            transport=transport,
        )

    def get(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = self._request("GET", url, params=params)
        if not isinstance(payload, dict):
            raise DownstreamError(
                self.service,
                200,
                "response root must be an object",
            )
        return payload

    def get_list(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        payload = self._request("GET", url, params=params)
        if not isinstance(payload, list) or not all(
            isinstance(item, dict) for item in payload
        ):
            raise DownstreamError(
                self.service,
                200,
                "response root must be an array of objects",
            )
        return payload

    def post(
        self,
        url: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        response = self._request("POST", url, json=payload)
        if not isinstance(response, dict):
            raise DownstreamError(
                self.service,
                200,
                "response root must be an object",
            )
        return response

    def _request(
        self,
        method: str,
        url: str,
        **kwargs: Any,
    ) -> dict[str, Any] | list[Any]:
        try:
            response = self.client.request(method, url, **kwargs)
        except httpx.HTTPError as exc:
            raise DownstreamError(
                self.service,
                None,
                f"{type(exc).__name__}: {exc}",
            ) from exc
        if response.is_error:
            detail = response.text
            try:
                body = response.json()
                detail = str(body.get("detail") or body)
            except ValueError:
                pass
            raise DownstreamError(
                self.service,
                response.status_code,
                detail,
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise DownstreamError(
                self.service,
                response.status_code,
                "response was not JSON",
            ) from exc
        if not isinstance(payload, (dict, list)):
            raise DownstreamError(
                self.service,
                response.status_code,
                "response root must be an object or array",
            )
        return payload


def proxy_http_request(
    *,
    service: str,
    base_url: str,
    method: str,
    path: str,
    query: str,
    headers: list[tuple[str, str]],
    body: bytes,
    transport: httpx.BaseTransport | None = None,
) -> ProxyResponse:
    allowed_request_headers = {
        "accept",
        "accept-language",
        "content-type",
        "cookie",
        "origin",
        "referer",
        "user-agent",
        "x-clink-console-token",
        "x-csrf-token",
    }
    forwarded_headers = [
        (name, value)
        for name, value in headers
        if name.lower() in allowed_request_headers
    ]
    url = f"{base_url.rstrip('/')}{path}"
    if query:
        url = f"{url}?{query}"
    try:
        with httpx.Client(
            timeout=15,
            transport=transport,
            follow_redirects=False,
        ) as client:
            response = client.request(
                method,
                url,
                headers=forwarded_headers,
                content=body,
            )
    except httpx.HTTPError as exc:
        raise DownstreamError(
            service,
            None,
            f"{type(exc).__name__}: {exc}",
        ) from exc
    allowed_response_headers = {
        "cache-control",
        "content-security-policy",
        "content-type",
        "location",
        "referrer-policy",
        "set-cookie",
        "x-content-type-options",
        "x-frame-options",
    }
    return ProxyResponse(
        status_code=response.status_code,
        content=response.content,
        headers=tuple(
            (name, value)
            for name, value in response.headers.multi_items()
            if name.lower() in allowed_response_headers
        ),
    )
