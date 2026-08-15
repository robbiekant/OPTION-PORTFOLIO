"""Provider protocol. Every data source implements this interface."""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..models import OptionQuote, UnderlyingSnapshot


@runtime_checkable
class MarketDataProvider(Protocol):
    name: str

    def available(self) -> bool:
        """Cheap health check. Never raises."""
        ...

    def underlying(self, symbol: str) -> UnderlyingSnapshot | None:
        """Spot, IV, HV and IV percentile for one underlying."""
        ...

    def chain(self, symbol: str, expiry: str,
              lo: float, hi: float) -> list[OptionQuote]:
        """All strikes between lo and hi for one expiration."""
        ...

    def expirations(self, symbol: str) -> list[str]:
        """Available expirations as YYYY-MM-DD, ascending."""
        ...

    def daily_closes(self, symbol: str, days: int) -> list[float]:
        """Adjusted daily closes, oldest first. Used for correlations."""
        ...


class ProviderError(RuntimeError):
    pass


def first_available(providers: list[MarketDataProvider]) -> MarketDataProvider | None:
    for p in providers:
        try:
            if p.available():
                return p
        except Exception:
            continue
    return None
