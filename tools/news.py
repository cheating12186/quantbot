"""Optional news providers; absence of a provider is explicit, never fabricated."""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any


class NewsUnavailable(RuntimeError):
    pass


class NewsProvider(ABC):
    name = "abstract"

    @abstractmethod
    def fetch(self, symbol: str, limit: int = 10) -> list[dict[str, Any]]:
        raise NotImplementedError


class NullNewsProvider(NewsProvider):
    name = "none"

    def fetch(self, symbol: str, limit: int = 10) -> list[dict[str, Any]]:
        raise NewsUnavailable("No news provider is configured")


class YFinanceNewsProvider(NewsProvider):
    name = "yfinance"

    def fetch(self, symbol: str, limit: int = 10) -> list[dict[str, Any]]:
        normalized = symbol.strip().upper().replace("/", "_")
        compact = normalized.replace("_", "")
        yahoo_symbol = f"{compact}=X" if "_" in normalized and len(compact) == 6 and compact.isalpha() else normalized
        try:
            import yfinance as yf
            raw = yf.Ticker(yahoo_symbol).news or []
        except Exception as exc:
            raise NewsUnavailable(f"Yahoo Finance news retrieval failed: {exc}") from exc
        items: list[dict[str, Any]] = []
        for entry in raw[:limit]:
            # Support both legacy and current yfinance response layouts.
            content = entry.get("content", entry)
            provider = content.get("provider", {}) or {}
            canonical = content.get("canonicalUrl", {}) or content.get("clickThroughUrl", {}) or {}
            published = content.get("pubDate") or content.get("providerPublishTime")
            published_at = None
            if isinstance(published, (int, float)):
                published_at = datetime.fromtimestamp(published, tz=timezone.utc)
            elif isinstance(published, str):
                try:
                    published_at = datetime.fromisoformat(published.replace("Z", "+00:00"))
                except ValueError:
                    pass
            items.append({
                "title": content.get("title", "Untitled"),
                "source": provider.get("displayName") or content.get("publisher", "unknown"),
                "url": canonical.get("url", "") if isinstance(canonical, dict) else str(canonical),
                "published_at": published_at,
                "summary": content.get("summary", ""),
            })
        return items


def build_news_provider(name: str):
    if name in ("yfinance", "yahoo"):
        return YFinanceNewsProvider()
    return NullNewsProvider()
