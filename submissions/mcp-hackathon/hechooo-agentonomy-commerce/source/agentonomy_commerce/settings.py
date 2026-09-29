"""Explicit configuration for a single-tenant review service."""
from dataclasses import dataclass
import os
from pathlib import Path
import re
from urllib.parse import urlsplit


@dataclass(frozen=True)
class Settings:
    state_dir: Path
    api_token: str
    source_commit: str
    project_slug: str
    merchant_port: int = 18081
    requests_per_minute: int = 60
    demo_origin: str | None = None

    def __post_init__(self):
        if not re.fullmatch(r"[\x21-\x7e]{32,256}", self.api_token):
            raise ValueError("a 32-256 character private review token is required")
        if not re.fullmatch(r"[0-9a-f]{40}", self.source_commit):
            raise ValueError("an exact 40-character source commit is required")
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", self.project_slug) or len(self.project_slug) > 100:
            raise ValueError("invalid project slug")
        if not 1 <= self.merchant_port <= 65535 or not 1 <= self.requests_per_minute <= 600:
            raise ValueError("invalid port or rate limit")
        if self.demo_origin is not None:
            origin = self.demo_origin
            parsed = urlsplit(origin)
            if (not origin.isascii() or any(c.isspace() for c in origin)
                    or parsed.scheme not in ("https", "http") or not parsed.hostname
                    or parsed.username is not None or parsed.password is not None
                    or parsed.path not in ("", "/") or parsed.query or parsed.fragment
                    or "?" in origin or "#" in origin or "\\" in origin
                    or (parsed.scheme == "http" and parsed.hostname not in ("localhost", "127.0.0.1", "::1"))):
                raise ValueError("demo origin must be an exact HTTPS origin (HTTP allowed only on localhost)")
            port = parsed.port
            host = parsed.hostname.lower()
            host = f"[{host}]" if ":" in host else host
            port_suffix = f":{port}" if port and port != (443 if parsed.scheme == "https" else 80) else ""
            object.__setattr__(self, "demo_origin", f"{parsed.scheme}://{host}{port_suffix}")
        object.__setattr__(self, "state_dir", Path(self.state_dir).expanduser().resolve())

    @classmethod
    def from_environment(cls):
        return cls(
            state_dir=Path(os.environ.get("AGENTONOMY_STATE_DIR", ".runtime/review")),
            api_token=os.environ.get("AGENTONOMY_API_TOKEN", ""),
            source_commit=os.environ.get("AGENTONOMY_SOURCE_COMMIT", ""),
            project_slug=os.environ.get("AGENTONOMY_PROJECT_SLUG", "hechooo-agentonomy-commerce"),
            merchant_port=int(os.environ.get("AGENTONOMY_MERCHANT_PORT", "18081")),
            demo_origin=os.environ.get("AGENTONOMY_DEMO_ORIGIN") or None,
            requests_per_minute=int(os.environ.get("AGENTONOMY_REQUESTS_PER_MINUTE", "60")),
        )
