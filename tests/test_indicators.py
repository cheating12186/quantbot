import numpy as np
import pandas as pd
import pytest

from tools.indicators import (
    add_indicators,
    atr,
    bollinger_bands,
    crossed_above,
    crossed_below,
    ema,
    macd,
    relative_volume,
    rsi,
    sma,
    vwap,
)


def test_ema_and_sma_known_values():
    values = pd.Series([1.0, 2.0, 3.0, 4.0])
    assert sma(values, 2).tolist()[-1] == 3.5
    # adjust=False EMA with span=3: alpha=2/(3+1)=0.5, seeded with first observation.
    expected = 1.0
    for value in values.iloc[1:]:
        expected = 0.5 * value + 0.5 * expected
    assert ema(values, 3).iloc[-1] == pytest.approx(expected)


def test_rsi_extremes_and_flat_series():
    increasing = pd.Series(np.arange(1.0, 40.0))
    assert rsi(increasing).iloc[-1] == 100.0
    flat = pd.Series([10.0] * 40)
    assert rsi(flat).iloc[-1] == 50.0


def test_macd_atr_and_bollinger_shapes(ohlcv):
    enriched = add_indicators(ohlcv)
    assert {"ema_9", "ema_200", "macd_hist", "atr_14", "bb_width", "vwap", "relative_volume"}.issubset(enriched)
    assert len(macd(ohlcv.close)) == len(ohlcv)
    assert atr(ohlcv).iloc[-1] > 0
    bands = bollinger_bands(ohlcv.close)
    assert bands.bb_upper.iloc[-1] > bands.bb_middle.iloc[-1] > bands.bb_lower.iloc[-1]


def test_vwap_known_values():
    index = pd.date_range("2024-01-01", periods=2, freq="h", tz="UTC")
    frame = pd.DataFrame({"high": [11, 13], "low": [9, 11], "close": [10, 12], "volume": [100, 100]}, index=index)
    assert vwap(frame).iloc[-1] == pytest.approx(11.0)


def test_relative_volume_excludes_current_observation():
    volume = pd.Series([100.0] * 20 + [1000.0])
    assert relative_volume(volume, 20).iloc[-1] == pytest.approx(10.0)


def test_cross_detection_requires_previous_bar():
    fast = pd.Series([1.0, 3.0])
    slow = pd.Series([2.0, 2.0])
    assert crossed_above(fast, slow)
    assert not crossed_below(fast, slow)
    assert not crossed_above(fast.iloc[:1], slow.iloc[:1])
