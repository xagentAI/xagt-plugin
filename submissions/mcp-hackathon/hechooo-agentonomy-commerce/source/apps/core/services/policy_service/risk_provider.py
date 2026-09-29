from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


class RiskProviderError(RuntimeError):
    """Raised when a risk provider cannot produce an assessment."""

    def __init__(self, message: str, *, category: str = "provider_error") -> None:
        super().__init__(message)
        self.category = category


@dataclass(frozen=True)
class RiskProviderResult:
    provider: str
    endpoint: str
    subject: str
    network: str
    asset: str
    coin: str
    score: int
    risk_level: str
    indicators: tuple[str, ...]
    risk_details: tuple[dict[str, str], ...]
    hacking_event: str | None
    assessed_at: datetime
    expires_at: datetime
    response_sha256: str
    cache_hit: bool = False


class RiskProvider(Protocol):
    def assess(
        self,
        *,
        subject: str,
        network: str,
        asset: str = "USDC",
    ) -> RiskProviderResult: ...
