from __future__ import annotations

import yfinance as yf

from tools.news import YFinanceNewsProvider


def _news_payload():
    return [{
        "content": {
            "title": "Euro strengthens after policy update",
            "summary": "A deterministic provider fixture",
            "provider": {"displayName": "Example Newswire"},
            "canonicalUrl": {"url": "https://example.test/euro-policy"},
            "pubDate": "2026-11-09T03:00:00Z",
        }
    }]


def test_yfinance_news_normalizes_forex_instrument(monkeypatch):
    requested = []

    class Ticker:
        def __init__(self, symbol):
            requested.append(symbol)
            self.news = _news_payload()

    monkeypatch.setattr(yf, "Ticker", Ticker)
    items = YFinanceNewsProvider().fetch("EUR_USD")

    assert requested == ["EURUSD=X"]
    assert items[0]["title"] == "Euro strengthens after policy update"
    assert items[0]["source"] == "Example Newswire"
    assert items[0]["url"] == "https://example.test/euro-policy"
    assert items[0]["published_at"].isoformat() == "2026-11-09T03:00:00+00:00"


def test_yfinance_news_preserves_equity_symbol(monkeypatch):
    requested = []

    class Ticker:
        def __init__(self, symbol):
            requested.append(symbol)
            self.news = []

    monkeypatch.setattr(yf, "Ticker", Ticker)
    assert YFinanceNewsProvider().fetch("aapl") == []
    assert requested == ["AAPL"]
