from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from tools.market_data import (
    MarketDataError,
    MarketDataService,
    MarketDataValidationError,
    SyntheticMarketDataProvider,
    inspect_market_data,
    normalize_ohlcv,
    validate_market_data,
)


class FailingProvider:
    name = "failing"
    is_synthetic = False

    def history(self, symbol, timeframe, rows=300):
        raise MarketDataError("network unavailable")


def test_retrieval_failure_without_fallback():
    service = MarketDataService(provider=FailingProvider())
    with pytest.raises(MarketDataError, match="network unavailable"):
        service.fetch("AAPL", "1d")


def test_retrieval_failure_uses_labelled_synthetic_fallback(now):
    service = MarketDataService(provider=FailingProvider(), fallback=SyntheticMarketDataProvider(), clock=lambda: now)
    result = service.fetch("AAPL", "1d", rows=100)
    assert result.is_synthetic
    assert result.source == "synthetic"
    assert "SYNTHETIC_FALLBACK" in [issue.code for issue in result.quality.issues]


def test_missing_data_is_rejected(ohlcv):
    broken = ohlcv.copy()
    broken.iloc[4, 3] = float("nan")
    with pytest.raises(MarketDataValidationError, match="missing"):
        validate_market_data(broken, min_rows=30)


def test_missing_column_is_rejected(ohlcv):
    with pytest.raises(MarketDataValidationError, match="Missing columns"):
        validate_market_data(ohlcv.drop(columns="volume"))


def test_stale_data_is_detected(ohlcv):
    now = ohlcv.index[-1].to_pydatetime() + timedelta(days=5)
    quality = inspect_market_data(ohlcv, now=now, max_age_minutes=60)
    assert not quality.valid
    assert "STALE" in [issue.code for issue in quality.issues]


def test_duplicate_timestamps_removed_and_timezone_normalized(ohlcv):
    naive = ohlcv.copy()
    naive.index = naive.index.tz_localize(None)
    duplicated = pd.concat([naive, naive.iloc[[3]]])
    normalized = normalize_ohlcv(duplicated)
    assert normalized.index.tz is not None
    assert normalized.index.is_unique
    assert normalized.index.is_monotonic_increasing
    assert len(normalized) == len(naive)


def test_invalid_ohlc_relationship_is_rejected(ohlcv):
    broken = ohlcv.copy()
    broken.iloc[2, broken.columns.get_loc("high")] = 0.01
    with pytest.raises(MarketDataValidationError, match="invalid OHLCV"):
        validate_market_data(broken)


def test_empty_provider_response_is_rejected():
    quality = inspect_market_data(pd.DataFrame())
    assert not quality.valid
    assert quality.issues[0].code == "EMPTY"
