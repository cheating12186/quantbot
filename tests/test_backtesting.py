import numpy as np
import pandas as pd
import pytest

from tools.backtesting import BacktestConfig, chronological_split, run_ema_crossover_backtest
from tools.risk_calculations import max_drawdown, sharpe_ratio, trade_statistics


def crossover_data(ohlcv):
    close = 100 + np.linspace(0, 10, len(ohlcv)) + 10 * np.sin(np.arange(len(ohlcv)) / 5)
    open_ = np.r_[close[0], close[:-1]]
    return pd.DataFrame({
        "open": open_, "high": np.maximum(open_, close) + 1,
        "low": np.minimum(open_, close) - 1, "close": close, "volume": ohlcv.volume.values,
    }, index=ohlcv.index)


def test_backtest_produces_real_equity_trades_and_benchmark(ohlcv):
    ohlcv = crossover_data(ohlcv)
    result = run_ema_crossover_backtest(ohlcv, BacktestConfig())
    assert result.rows == len(ohlcv)
    assert len(result.equity_curve) == len(ohlcv) - 1
    assert result.final_equity > 0
    assert len(result.trades) > 0
    assert result.buy_and_hold_return_pct != 0
    assert all(trade.fees > 0 for trade in result.trades)


def test_backtest_uses_next_bar_after_signal(ohlcv):
    result = run_ema_crossover_backtest(crossover_data(ohlcv))
    assert result.trades
    assert all(trade.signal_timestamp < trade.entry_timestamp for trade in result.trades)
    assert all(trade.entry_timestamp <= trade.exit_timestamp for trade in result.trades)


def test_future_price_change_cannot_change_prior_entries(ohlcv):
    ohlcv = crossover_data(ohlcv)
    config = BacktestConfig()
    original = run_ema_crossover_backtest(ohlcv, config)
    changed = ohlcv.copy()
    # A last-bar mutation must not retroactively change any earlier entry.
    changed.iloc[-1, changed.columns.get_loc("close")] *= 5
    changed.iloc[-1, changed.columns.get_loc("high")] *= 5
    mutated = run_ema_crossover_backtest(changed, config)
    original_entries = [(t.entry_timestamp, t.entry_price) for t in original.trades if t.entry_timestamp < ohlcv.index[-1].to_pydatetime()]
    mutated_entries = [(t.entry_timestamp, t.entry_price) for t in mutated.trades if t.entry_timestamp < ohlcv.index[-1].to_pydatetime()]
    assert original_entries == mutated_entries


def test_chronological_split_never_shuffles(ohlcv):
    train, test = chronological_split(ohlcv, 0.7)
    assert train.index[-1] < test.index[0]
    assert len(train) + len(test) == len(ohlcv)


def test_risk_metrics_known_values():
    assert max_drawdown([100, 120, 60, 90]) == pytest.approx(0.5)
    stats = trade_statistics([10, 20, -10])
    assert stats["win_rate"] == pytest.approx(2 / 3)
    assert stats["profit_factor"] == pytest.approx(3)
    assert stats["expectancy"] == pytest.approx(20 / 3)
    assert sharpe_ratio([0.01]) == 0
