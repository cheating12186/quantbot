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
