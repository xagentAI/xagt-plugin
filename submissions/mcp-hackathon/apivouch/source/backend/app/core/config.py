import ipaddress
import os
import re
from urllib.parse import urlsplit

APP_NAME = "apivouch"
APP_VERSION = "1.2.0"
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./apivouch.db")
ALLOW_PRIVATE_NETWORK = os.getenv("ALLOW_PRIVATE_NETWORK", "false").lower() == "true"
REQUEST_TIMEOUT = float(os.getenv("REQUEST_TIMEOUT", "10"))
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "1"))
MAX_RESPONSE_BYTES = int(os.getenv("MAX_RESPONSE_BYTES", "1048576"))
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", "524288"))
MAX_MCP_REQUEST_BYTES = int(os.getenv("MAX_MCP_REQUEST_BYTES", "1048576"))
MAX_ENDPOINTS = int(os.getenv("MAX_ENDPOINTS", "200"))
MAX_PROJECTS = int(os.getenv("MAX_PROJECTS", "250"))
MAX_OUTCOME_RECEIPTS = int(os.getenv("MAX_OUTCOME_RECEIPTS", "1000"))
MAX_REDIRECTS = int(os.getenv("MAX_REDIRECTS", "3"))
MAX_PROOF_PAGES = int(os.getenv("MAX_PROOF_PAGES", "20"))
MAX_PROOF_RECORDS = int(os.getenv("MAX_PROOF_RECORDS", "5000"))
GIT_COMMIT = os.getenv("GIT_COMMIT") or os.getenv("RENDER_GIT_COMMIT") or "dev-local"
PROJECT_SLUG = os.getenv("PROJECT_SLUG", "apivouch")


def validate_public_base_url(value: str) -> str:
    if not value:
        return ""
    try:
        if len(value) > 2048 or any(ord(c) <= 32 or ord(c) >= 127 for c in value) or any(c in value for c in "\\?#%"):
            raise ValueError
        parts = urlsplit(value)
        host = parts.hostname
        if not host or parts.username is not None or parts.password is not None or parts.path not in {"", "/"}:
            raise ValueError
        if parts.port == 0 or parts.netloc.endswith(":"):
            raise ValueError
        try:
            loopback = ipaddress.ip_address(host).is_loopback
        except ValueError:
            loopback = host == "localhost"
            if len(host) > 253 or any(re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", label) is None for label in host.split(".")):
                raise ValueError
        if parts.scheme != "https" and not (parts.scheme == "http" and loopback):
            raise ValueError
        return value.removesuffix("/")
    except ValueError:
        raise ValueError("Invalid public origin") from None


PUBLIC_BASE_URL_CONFIGURED = bool(os.getenv("PUBLIC_BASE_URL", ""))
try:
    PUBLIC_BASE_URL = validate_public_base_url(os.getenv("PUBLIC_BASE_URL", ""))
    PUBLIC_BASE_URL_VALID = True
except ValueError:
    PUBLIC_BASE_URL = ""
    PUBLIC_BASE_URL_VALID = False


def deployment_config_ready() -> bool:
    return PUBLIC_BASE_URL_VALID and (not PUBLIC_BASE_URL_CONFIGURED or (
        PROJECT_SLUG == "apivouch" and re.fullmatch(r"[0-9a-f]{40}", GIT_COMMIT) is not None
    ))


CORS_ORIGINS = [v.strip() for v in os.getenv("CORS_ORIGINS", "").split(",") if v.strip()]
