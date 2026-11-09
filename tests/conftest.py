from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest


@pytest.fixture
def ohlcv() -> pd.DataFrame:
    rng = np.random.default_rng(42)
    rows = 260
    index = pd.date_range("2024-01-01", periods=rows, freq="D", tz="UTC")
    close = 100 + np.linspace(0, 30, rows) + np.sin(np.arange(rows) / 4)
    open_ = close + rng.normal(0, 0.3, rows)
    high = np.maximum(open_, close) + 1
    low = np.minimum(open_, close) - 1
    volume = rng.integers(1000, 5000, rows).astype(float)
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": volume}, index=index)


@pytest.fixture
def flat_ohlcv() -> pd.DataFrame:
    index = pd.date_range("2024-01-01", periods=60, freq="D", tz="UTC")
    return pd.DataFrame({"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 1000.0}, index=index)


@pytest.fixture
def now() -> datetime:
    return datetime(2024, 9, 16, tzinfo=timezone.utc)
