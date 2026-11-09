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


# ---------------------------------------------------------------------------
# Provider factory, fallback chain, caching, and diagnostics
# ---------------------------------------------------------------------------
import httpx
import pytest

from agents.news_analyst import NewsSentimentAnalyst
from models.agent_outputs import AgentStatus
from tools.news import (
    ChainedNewsProvider,
    FinnhubNewsProvider,
    NewsUnavailable,
    NullNewsProvider,
    TTLNewsCache,
    YFinanceNewsProvider as _YF,
    build_news_provider,
    dedupe_articles,
    describe_news_chain,
)


def _client_for(handler):
    client = httpx.Client(
        base_url="https://finnhub.io/api/v1",
        transport=httpx.MockTransport(handler),
        headers={"X-Finnhub-Token": "test-key"},
    )
    return client


def _finnhub_items(n=2):
    return [
        {"id": i, "headline": f"Headline {i}", "source": "Newswire", "url": f"https://example.test/article-{i}",
         "datetime": 1794200000 + i * 1000, "summary": "Summary", "related": "EUR_USD"}
        for i in range(n)
    ]


def test_finnhub_forex_path_uses_forex_category():
    seen = {}

    def handler(request: httpx.Request):
        seen["path"] = request.url.path
        seen["params"] = dict(request.url.params)
        seen["token"] = request.headers.get("X-Finnhub-Token")
        return httpx.Response(200, json=_finnhub_items(3))

    provider = FinnhubNewsProvider("test-key", client=_client_for(handler), sleeper=lambda *_: None)
    items = provider.fetch("EUR_USD")
    assert seen["path"] == "/api/v1/news"
    assert seen["params"]["category"] == "forex"
    assert seen["token"] == "test-key"
    assert len(items) == 3
    assert items[0]["published_at"] is not None
    assert provider.last_report["availability"] == "AVAILABLE"


def test_finnhub_equity_path_uses_company_news():
    seen = {}

    def handler(request: httpx.Request):
        seen["path"] = request.url.path
        seen["params"] = dict(request.url.params)
        return httpx.Response(200, json=_finnhub_items(1))

    provider = FinnhubNewsProvider("test-key", client=_client_for(handler), sleeper=lambda *_: None)
    provider.fetch("AAPL")
    assert seen["path"] == "/api/v1/company-news"
    assert seen["params"]["symbol"] == "AAPL"
    assert "from" in seen["params"] and "to" in seen["params"]


def test_finnhub_without_key_fails_explicitly():
    provider = build_news_provider("finnhub")
    assert isinstance(provider, NullNewsProvider)
    with pytest.raises(NewsUnavailable) as excinfo:
        provider.fetch("EUR_USD")
    assert excinfo.value.category == "NOT_CONFIGURED"


def test_build_news_provider_auto_uses_finnhub_then_yfinance(monkeypatch):
    called = []

    class FakeFinnhub(FinnhubNewsProvider):
        def __init__(self, key, **kwargs):
            self.name = "finnhub"
            self._cache = None
            self._sleep = lambda *_: None
            self.last_report = None

        def _fetch(self, symbol, limit):
            called.append("finnhub")
            raise NewsUnavailable("Finnhub rejected the configured API key (HTTP 401)", "AUTH_ERROR")

    monkeypatch.setattr("tools.news.FinnhubNewsProvider", FakeFinnhub)
    monkeypatch.setattr(yf, "Ticker", type("Ticker", (), {"__init__": lambda self, s: None, "news": _news_payload()}))
    provider = build_news_provider("auto", finnhub_api_key="test-key", cache_ttl_seconds=0)
    assert [p.name for p in provider.providers] == ["finnhub", "yfinance"]
    items = provider.fetch("EUR_USD")
    assert called == ["finnhub"]
    assert items and provider.last_report["provider"] == "yfinance"
    categories = [a.get("category") for a in provider.last_report["attempts"] if not a["ok"]]
    assert categories == ["AUTH_ERROR"]


def test_chain_all_providers_fail_raises_with_sanitized_categories():
    class BrokenFinnhub(FinnhubNewsProvider):
        def __init__(self):
            self.name = "finnhub"
            self._cache = None
            self._sleep = lambda *_: None
            self.last_report = None

        def _fetch(self, symbol, limit):
            raise NewsUnavailable("token=supersecret rejected", "RATE_LIMITED")

    class BrokenYahoo(_YF):
        def _fetch(self, symbol, limit):
            raise NewsUnavailable("Yahoo is down", "PROVIDER_ERROR")

    chain = ChainedNewsProvider([BrokenFinnhub(), BrokenYahoo()], cache=None)
    with pytest.raises(NewsUnavailable):
        chain.fetch("EUR_USD")
    report = chain.last_report
    assert report["availability"] == "UNAVAILABLE"
    assert [a["category"] for a in report["attempts"]] == ["RATE_LIMITED", "PROVIDER_ERROR"]
    assert "supersecret" not in str(report)


def test_chain_empty_is_distinct_from_failure():
    class EmptyOk(_YF):
        def _fetch(self, symbol, limit):
            return []

    chain = ChainedNewsProvider([EmptyOk()], cache=None)
    assert chain.fetch("EUR_USD") == []
    assert chain.last_report["availability"] == "EMPTY"
    assert chain.last_report["attempts"][0]["ok"] is True


def test_dedupe_articles_by_url_and_headline():
    items = [
        {"title": "A", "url": "https://x.test/a"},
        {"title": "A again", "url": "https://x.test/a#fragment"},
        {"title": "B", "url": ""},
        {"title": "b", "url": ""},
        {"title": "C", "url": "https://x.test/c"},
    ]
    deduped = dedupe_articles(items)
    assert [i["title"] for i in deduped] == ["A", "B", "C"]


def test_finnhub_invalid_items_are_dropped_never_invented():
    payload = [
        {"headline": "", "url": "https://example.test/empty"},          # no headline -> dropped
        {"source": "Newswire"},                                        # no headline -> dropped
        {"headline": "Real headline", "source": "Newswire", "url": "https://example.test/real", "datetime": "not-a-number"},
    ]

    def handler(request: httpx.Request):
        return httpx.Response(200, json=payload)

    provider = FinnhubNewsProvider("test-key", client=_client_for(handler), sleeper=lambda *_: None)
    items = provider.fetch("EUR_USD")
    assert [i["title"] for i in items] == ["Real headline"]
    assert items[0]["published_at"] is None  # not fabricated


def test_finnhub_rate_limit_retries_then_reports():
    calls = []

    def handler(request: httpx.Request):
        calls.append(1)
        return httpx.Response(429, json={"error": "rate limit"}, headers={"Retry-After": "0"})

    provider = FinnhubNewsProvider("test-key", client=_client_for(handler), sleeper=lambda *_: None)
    with pytest.raises(NewsUnavailable) as excinfo:
        provider.fetch("EUR_USD")
    assert excinfo.value.category == "RATE_LIMITED"
    assert len(calls) == 3


def test_finnhub_timeout_is_retried_then_network_error():
    calls = []

    def handler(request: httpx.Request):
        calls.append(1)
        raise httpx.ConnectTimeout("timed out", request=request)

    provider = FinnhubNewsProvider("test-key", client=_client_for(handler), sleeper=lambda *_: None)
    with pytest.raises(NewsUnavailable) as excinfo:
        provider.fetch("EUR_USD")
    assert excinfo.value.category == "NETWORK_ERROR"
    assert len(calls) == 3


def test_finnhub_auth_error_is_not_retried():
    calls = []

    def handler(request: httpx.Request):
        calls.append(1)
        return httpx.Response(401, json={"error": "bad token"})

    provider = FinnhubNewsProvider("test-key", client=_client_for(handler), sleeper=lambda *_: None)
    with pytest.raises(NewsUnavailable) as excinfo:
        provider.fetch("EUR_USD")
    assert excinfo.value.category == "AUTH_ERROR"
    assert len(calls) == 1


def test_cache_hit_avoids_repeat_requests_and_preserves_retrieval_time():
    calls = []

    def handler(request: httpx.Request):
        calls.append(1)
        return httpx.Response(200, json=_finnhub_items(1))

    ticks = iter([1000.0, 1005.0])  # fetch1: clock in set() = 1000; fetch2: clock in get() = 1005 (within TTL)
    cache = TTLNewsCache(ttl_seconds=300, clock=lambda: next(ticks))
    provider = FinnhubNewsProvider("test-key", client=_client_for(handler), cache=cache, sleeper=lambda *_: None)
    first = provider.fetch("EUR_USD")
    second = provider.fetch("EUR_USD")
    assert len(calls) == 1
    assert len(first) == len(second) == 1
    assert provider.last_report["cache_hit"] is True
    assert provider.last_report["retrieved_at"]


def test_cache_ttl_expiry_refetches():
    calls = []

    def handler(request: httpx.Request):
        calls.append(1)
        return httpx.Response(200, json=_finnhub_items(1))

    ticks = iter([1000.0, 2000.0, 2000.0])  # fetch1 set() = 1000; fetch2 get() = 2000 (> TTL); refetch set() = 2000
    cache = TTLNewsCache(ttl_seconds=60, clock=lambda: next(ticks))
    provider = FinnhubNewsProvider("test-key", client=_client_for(handler), cache=cache, sleeper=lambda *_: None)
    provider.fetch("EUR_USD")
    provider.fetch("EUR_USD")
    assert len(calls) == 2


def test_news_analyst_reports_unavailable_explicitly(monkeypatch):
    class AlwaysDown(NullNewsProvider):
        pass

    output = NewsSentimentAnalyst(NullNewsProvider()).analyze("EUR_USD", span=_span())
    assert output.status == AgentStatus.UNAVAILABLE
    assert output.availability == "UNAVAILABLE"
    assert output.items == []
    assert output.diagnostics["availability"] == "UNAVAILABLE"
    assert "no news claims were generated" in output.explanation


def test_news_analyst_distinguishes_empty_from_unavailable():
    class EmptyProvider(_YF):
        def _fetch(self, symbol, limit):
            return []

    empty = NewsSentimentAnalyst(EmptyProvider(cache=None)).analyze("EUR_USD", span=_span())
    assert empty.status == AgentStatus.SUCCESS
    assert empty.availability == "EMPTY"


def _span():
    from models.agent_outputs import TraceSpan
    return TraceSpan(agent="News & Sentiment Analyst")


def test_describe_news_chain_reports_configuration():
    assert describe_news_chain("auto", True) == ["finnhub", "yfinance"]
    assert describe_news_chain("auto", False) == ["yfinance"]
    assert describe_news_chain("none") == []
    assert describe_news_chain("finnhub") == ["finnhub"]
