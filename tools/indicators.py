"""Vectorised technical indicators implemented with pandas/numpy only."""
from __future__ import annotations

import numpy as np
import pandas as pd


def ema(series: pd.Series, period: int) -> pd.Series:
    if period < 1:
        raise ValueError("EMA period must be positive")
    return series.astype(float).ewm(span=period, adjust=False, min_periods=period).mean()


def sma(series: pd.Series, period: int) -> pd.Series:
    if period < 1:
        raise ValueError("SMA period must be positive")
    return series.astype(float).rolling(period, min_periods=period).mean()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """Wilder's RSI; initial average uses an exponential Wilder smoothing."""
    if period < 1:
        raise ValueError("RSI period must be positive")
    delta = series.astype(float).diff()
    gains = delta.clip(lower=0)
    losses = -delta.clip(upper=0)
    avg_gain = gains.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = losses.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    result = 100 - 100 / (1 + rs)
    result = result.mask((avg_loss == 0) & (avg_gain > 0), 100.0)
    result = result.mask((avg_loss == 0) & (avg_gain == 0), 50.0)
    return result


def macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    if fast >= slow:
        raise ValueError("MACD fast period must be below slow period")
    line = ema(series, fast) - ema(series, slow)
    signal_line = line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    return pd.DataFrame({"macd": line, "macd_signal": signal_line, "macd_hist": line - signal_line})


def true_range(frame: pd.DataFrame) -> pd.Series:
    previous_close = frame["close"].shift(1)
    return pd.concat(
        [frame["high"] - frame["low"], (frame["high"] - previous_close).abs(), (frame["low"] - previous_close).abs()],
        axis=1,
    ).max(axis=1)


def atr(frame: pd.DataFrame, period: int = 14) -> pd.Series:
    return true_range(frame).ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def bollinger_bands(series: pd.Series, period: int = 20, deviations: float = 2.0) -> pd.DataFrame:
    middle = sma(series, period)
    standard_deviation = series.astype(float).rolling(period, min_periods=period).std(ddof=0)
    upper = middle + deviations * standard_deviation
    lower = middle - deviations * standard_deviation
    width = (upper - lower) / middle.replace(0, np.nan)
    return pd.DataFrame({"bb_lower": lower, "bb_middle": middle, "bb_upper": upper, "bb_width": width})


def vwap(frame: pd.DataFrame, session_anchored: bool = True) -> pd.Series:
    typical = (frame["high"] + frame["low"] + frame["close"]) / 3
    price_volume = typical * frame["volume"]
    if session_anchored and isinstance(frame.index, pd.DatetimeIndex):
        groups = frame.index.date
        cumulative_pv = price_volume.groupby(groups).cumsum()
        cumulative_volume = frame["volume"].groupby(groups).cumsum()
    else:
        cumulative_pv = price_volume.cumsum()
        cumulative_volume = frame["volume"].cumsum()
    return cumulative_pv / cumulative_volume.replace(0, np.nan)


def relative_volume(volume: pd.Series, period: int = 20) -> pd.Series:
    # Prior bars only: including the current bar would dilute the comparison.
    baseline = volume.astype(float).shift(1).rolling(period, min_periods=period).mean()
    return volume / baseline.replace(0, np.nan)


def support_resistance(frame: pd.DataFrame, lookback: int = 20) -> tuple[float, float]:
    if lookback < 2:
        raise ValueError("Lookback must be at least 2")
    # Exclude the active bar so support/resistance are known at signal time.
    window = frame.iloc[-lookback - 1:-1] if len(frame) > lookback else frame.iloc[:-1]
    if window.empty:
        window = frame
    return float(window["low"].min()), float(window["high"].max())


def add_indicators(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    for period in (9, 15, 20, 50, 200):
        result[f"ema_{period}"] = ema(result["close"], period)
    for period in (20, 50, 200):
        result[f"sma_{period}"] = sma(result["close"], period)
    result["rsi_14"] = rsi(result["close"])
    result = result.join(macd(result["close"]))
    result["atr_14"] = atr(result)
    result = result.join(bollinger_bands(result["close"]))
    result["vwap"] = vwap(result)
    result["relative_volume"] = relative_volume(result["volume"])
    result["returns"] = result["close"].pct_change()
    return result


def crossed_above(fast: pd.Series, slow: pd.Series) -> bool:
    if len(fast) < 2 or pd.isna(fast.iloc[-2:]).any() or pd.isna(slow.iloc[-2:]).any():
        return False
    return bool(fast.iloc[-2] <= slow.iloc[-2] and fast.iloc[-1] > slow.iloc[-1])


def crossed_below(fast: pd.Series, slow: pd.Series) -> bool:
    if len(fast) < 2 or pd.isna(fast.iloc[-2:]).any() or pd.isna(slow.iloc[-2:]).any():
        return False
    return bool(fast.iloc[-2] >= slow.iloc[-2] and fast.iloc[-1] < slow.iloc[-1])
