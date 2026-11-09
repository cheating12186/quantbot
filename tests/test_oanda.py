import httpx
import pytest

from tools.market_data import MarketDataError
from tools.oanda import OandaMarketDataProvider


def mock_provider():
    def handler(request: httpx.Request):
        assert request.headers["Authorization"] == "Bearer test-token"
        if "/candles" in request.url.path:
            return httpx.Response(200, json={"candles": [
                {"time": "2026-11-06T10:00:00Z", "complete": True, "volume": 100, "mid": {"o": "1.1000", "h": "1.1030", "l": "1.0990", "c": "1.1020"}},
                {"time": "2026-11-06T10:05:00Z", "complete": False, "volume": 20, "mid": {"o": "1.1020", "h": "1.1040", "l": "1.1010", "c": "1.1030"}},
            ]})
        if request.url.path.endswith("/pricing"):
            return httpx.Response(200, json={"prices": [{"time": "2026-11-06T10:06:00Z", "bids": [{"price": "1.1020"}], "asks": [{"price": "1.1024"}]}]})
        if request.url.path.endswith("/summary"):
            return httpx.Response(200, json={"account": {"id": "demo", "currency": "USD"}})
        return httpx.Response(404, json={"errorMessage": "unknown endpoint"})

    client = httpx.Client(base_url="https://api-fxpractice.oanda.com", transport=httpx.MockTransport(handler), headers={"Authorization": "Bearer test-token"})
    return OandaMarketDataProvider("test-token", "demo", client=client)


def test_oanda_instrument_normalization():
    assert OandaMarketDataProvider.instrument("EURUSD") == "EUR_USD"
    assert OandaMarketDataProvider.instrument("eur/usd") == "EUR_USD"
    assert OandaMarketDataProvider.instrument("GBP_USD") == "GBP_USD"
    with pytest.raises(MarketDataError):
        OandaMarketDataProvider.instrument("not-an-instrument")


def test_oanda_completed_candles_and_realtime_quote():
    provider = mock_provider()
    frame = provider.history("EURUSD", "5m", 60)
    assert len(frame) == 1  # Incomplete candle is excluded to prevent repainting.
    assert frame.index[0].tzinfo is not None
    assert frame.attrs["quote"]["mid"] == pytest.approx(1.1022)
    assert frame.attrs["environment"] == "practice"
    quote = provider.latest_price("EUR_USD")
    assert quote["spread"] == pytest.approx(0.0004)
    assert quote["is_synthetic"] is False


def test_oanda_account_metadata_is_data_only():
    summary = mock_provider().account_summary()
    assert summary == {"id": "demo", "currency": "USD", "environment": "practice", "data_only": True}


def test_oanda_live_environment_is_not_supported():
    with pytest.raises(MarketDataError, match="practice"):
        OandaMarketDataProvider("token", "account", environment="live")


# ---------------------------------------------------------------------------
# Forming (incomplete) candles: chart-only, never confirmed data
# ---------------------------------------------------------------------------
import json


def forming_provider(candles):
    def handler(request: httpx.Request):
        if "/candles" in request.url.path:
            return httpx.Response(200, json={"candles": candles})
        if request.url.path.endswith("/pricing"):
            return httpx.Response(200, json={"prices": [{"time": "2026-11-09T06:40:00Z", "bids": [{"price": "1.1020"}], "asks": [{"price": "1.1024"}]}]})
        if request.url.path.endswith("/summary"):
            return httpx.Response(200, json={"account": {"id": "demo", "currency": "USD"}})
        return httpx.Response(404, json={"errorMessage": "unknown endpoint"})

    client = httpx.Client(base_url="https://api-fxpractice.oanda.com", transport=httpx.MockTransport(handler), headers={"Authorization": "Bearer test-token"})
    return OandaMarketDataProvider("test-token", "demo", client=client)


MIXED = [
    {"time": "2026-11-09T06:35:00.123456789Z", "complete": True, "volume": 100, "mid": {"o": "1.1000", "h": "1.1030", "l": "1.0990", "c": "1.1020"}},
    {"time": "2026-11-09T06:40:00.987654321Z", "complete": False, "volume": 20, "mid": {"o": "1.1020", "h": "1.1040", "l": "1.1010", "c": "1.1030"}},
]


def test_forming_candle_is_returned_with_complete_flag_and_utc_normalized():
    payload = forming_provider(MIXED).forming_candle("EUR_USD", "5m")
    assert payload["forming"]["complete"] is False
    assert payload["forming"]["close"] == pytest.approx(1.1030)
    assert payload["forming"]["timestamp"] == "2026-11-09T06:40:00Z"  # canonical UTC, seconds precision
    assert payload["completed_tail"]["complete"] is True
    assert payload["completed_tail"]["timestamp"] == "2026-11-09T06:35:00Z"
    assert payload["retrieved_at"].endswith("Z")


def test_forming_candle_absent_at_market_close():
    payload = forming_provider([MIXED[0]]).forming_candle("EUR_USD", "5m")
    assert payload["forming"] is None
    assert payload["completed_tail"] is not None


def test_forming_candle_rejects_unsupported_timeframe():
    with pytest.raises(MarketDataError):
        forming_provider(MIXED).forming_candle("EUR_USD", "7m")


def test_malformed_candles_are_skipped_not_invented():
    broken = [
        {"time": "2026-11-09T06:35:00Z", "complete": True, "volume": 1, "mid": {"o": "x", "h": "1.2", "l": "1.1", "c": "1.15"}},
        {"time": "garbage", "complete": False, "volume": 1, "mid": {"o": "1.1", "h": "1.2", "l": "1.1", "c": "1.15"}},
        MIXED[1],
    ]
    payload = forming_provider(broken).forming_candle("EUR_USD", "5m")
    assert payload["forming"] is not None  # only the valid incomplete candle survives
    assert payload["completed_tail"] is None  # malformed completed candle is dropped, never repaired


def test_completed_history_excludes_forming_candle():
    frame = forming_provider(MIXED).history("EUR_USD", "5m", 60)
    assert len(frame) == 1
    assert frame.index[0].isoformat() == "2026-11-09T06:35:00+00:00"


def test_market_data_service_forming_candle_captures_errors_without_raising():
    from tools.market_data import MarketDataService

    service = MarketDataService(provider=forming_provider(MIXED))
    payload = service.forming_candle("EUR_USD", "5m")
    assert payload["forming"]["complete"] is False

    class BrokenProvider:
        name = "broken"
        is_synthetic = False

        def history(self, symbol, timeframe, rows=300):
            raise MarketDataError("outage")

        def forming_candle(self, symbol, timeframe):
            raise MarketDataError("outage")

    broken = MarketDataService(provider=BrokenProvider())
    payload = broken.forming_candle("EUR_USD", "5m")
    assert payload["forming"] is None
    assert "outage" in payload["error"]


def test_provider_without_forming_support_reports_none():
    from tools.market_data import MarketDataService

    class QuietProvider:
        name = "quiet"
        is_synthetic = False

        def history(self, symbol, timeframe, rows=300):
            import pandas as pd
            index = pd.date_range("2026-10-01", periods=70, freq="D", tz="UTC")
            return pd.DataFrame(
                {"open": 1.0, "high": 1.1, "low": 0.9, "close": 1.05, "volume": 1000.0}, index=index
            )

    service = MarketDataService(provider=QuietProvider())
    payload = service.forming_candle("EUR_USD", "1d")
    assert payload["forming"] is None
    assert "not" in payload["reason"].lower() or "does not" in payload["reason"].lower()


def test_research_and_backtest_path_excludes_forming_candle():
    """MarketDataService.fetch feeds research, backtests and the dashboard; the
    forming candle must never enter it."""
    import pandas as pd
    from tools.market_data import MarketDataService

    base = pd.Timestamp("2026-11-09T06:00:00Z")
    candles = []
    for offset in range(6):  # 6 completed 5m bars + 1 forming
        stamp = (base + pd.Timedelta(minutes=5 * offset)).strftime("%Y-%m-%dT%H:%M:%SZ")
        candles.append({"time": stamp, "complete": True, "volume": 100 + offset,
                        "mid": {"o": "1.1000", "h": "1.1030", "l": "1.0990", "c": "1.1020"}})
    forming_stamp = (base + pd.Timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
    candles.append({"time": forming_stamp, "complete": False, "volume": 5,
                    "mid": {"o": "1.1020", "h": "1.1040", "l": "1.1010", "c": "1.1030"}})

    service = MarketDataService(provider=forming_provider(candles))
    dataset = service.fetch("EUR_USD", "5m", rows=5)
    assert len(dataset.frame) == 5
    assert dataset.frame.index.max().strftime("%Y-%m-%dT%H:%M:%SZ") == "2026-11-09T06:25:00Z"
