"""Pure quantitative performance and trade-risk calculations."""
from __future__ import annotations

import math
from collections.abc import Iterable

import numpy as np
import pandas as pd


def _clean_returns(returns: Iterable[float] | pd.Series) -> np.ndarray:
    values = np.asarray(list(returns) if not isinstance(returns, pd.Series) else returns.values, dtype=float)
    return values[np.isfinite(values)]


def annualized_volatility(returns: Iterable[float] | pd.Series, periods_per_year: int = 252) -> float:
    values = _clean_returns(returns)
    return float(np.std(values, ddof=1) * math.sqrt(periods_per_year)) if len(values) > 1 else 0.0


def sharpe_ratio(returns: Iterable[float] | pd.Series, risk_free_rate: float = 0.0, periods_per_year: int = 252) -> float:
    values = _clean_returns(returns)
    if len(values) < 2:
        return 0.0
    excess = values - risk_free_rate / periods_per_year
    deviation = np.std(excess, ddof=1)
    return float(np.mean(excess) / deviation * math.sqrt(periods_per_year)) if deviation > 1e-12 else 0.0


def sortino_ratio(returns: Iterable[float] | pd.Series, risk_free_rate: float = 0.0, periods_per_year: int = 252) -> float:
    values = _clean_returns(returns)
    if len(values) < 2:
        return 0.0
    excess = values - risk_free_rate / periods_per_year
    downside = np.minimum(excess, 0)
    deviation = math.sqrt(float(np.mean(downside**2)))
    return float(np.mean(excess) / deviation * math.sqrt(periods_per_year)) if deviation > 1e-12 else 0.0


def drawdown_series(equity: Iterable[float] | pd.Series) -> pd.Series:
    values = pd.Series(equity, dtype=float)
    if values.empty:
        return values
    peaks = values.cummax()
    return values / peaks.replace(0, np.nan) - 1.0


def max_drawdown(equity: Iterable[float] | pd.Series) -> float:
    curve = drawdown_series(equity)
    return float(abs(curve.min())) if len(curve) and np.isfinite(curve.min()) else 0.0


def trade_statistics(pnls: Iterable[float]) -> dict[str, float | None]:
    values = _clean_returns(pnls)
    wins = values[values > 0]
    losses = values[values < 0]
    gross_profit = float(wins.sum())
    gross_loss = float(abs(losses.sum()))
    return {
        "trade_count": float(len(values)),
        "win_rate": float(len(wins) / len(values)) if len(values) else 0.0,
        # None denotes an undefined/infinite ratio when there are no losing trades;
        # this keeps API JSON standards-compliant without understating the ratio as zero.
        "profit_factor": gross_profit / gross_loss if gross_loss > 0 else None,
        "expectancy": float(values.mean()) if len(values) else 0.0,
        "average_win": float(wins.mean()) if len(wins) else 0.0,
        "average_loss": float(losses.mean()) if len(losses) else 0.0,
    }


def risk_reward(entry: float, stop: float, target: float, side: str) -> float:
    if side.upper() == "LONG":
        risk, reward = entry - stop, target - entry
    elif side.upper() == "SHORT":
        risk, reward = stop - entry, entry - target
    else:
        raise ValueError("Side must be LONG or SHORT")
    if risk <= 0 or reward <= 0:
        return 0.0
    return float(reward / risk)


def position_risk(entry: float, stop: float, quantity: float) -> float:
    if quantity < 0:
        raise ValueError("Quantity cannot be negative")
    return float(abs(entry - stop) * quantity)
