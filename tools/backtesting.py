"""Event-driven EMA-crossover backtester with next-bar execution.

Signals are formed at bar close and filled at the following bar's open. When a
stop and target occur inside one bar, the stop is assumed to occur first.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field

from models.portfolio import PerformanceMetrics
from tools.indicators import add_indicators
from tools.risk_calculations import annualized_volatility, drawdown_series, sharpe_ratio, sortino_ratio, trade_statistics


class BacktestConfig(BaseModel):
    fast_ema: int = Field(default=9, ge=2)
    slow_ema: int = Field(default=15, ge=3)
    initial_equity: float = Field(default=100_000, gt=0)
    risk_per_trade_pct: float = Field(default=0.01, gt=0, le=0.05)
    max_position_notional_pct: float = Field(default=0.25, gt=0, le=1)
    atr_stop_multiple: float = Field(default=1.5, gt=0)
    atr_target_multiple: float = Field(default=3.0, gt=0)
    fee_bps: float = Field(default=1.0, ge=0)
    slippage_bps: float = Field(default=2.0, ge=0)
    lot_size: float = Field(default=1.0, gt=0)
    allow_short: bool = True
    periods_per_year: int = Field(default=252, ge=1)

    def model_post_init(self, __context):
        if self.fast_ema >= self.slow_ema:
            raise ValueError("Fast EMA must be below slow EMA")


class EquityPoint(BaseModel):
    timestamp: datetime
    equity: float
    drawdown: float = 0.0
    buy_and_hold: float


class BacktestTrade(BaseModel):
    side: str
    signal_timestamp: datetime
    entry_timestamp: datetime
    exit_timestamp: datetime
    entry_price: float
    exit_price: float
    quantity: float
    stop_loss: float
    take_profit: float
    pnl: float
    return_pct: float
    exit_reason: str
    fees: float


class BacktestResult(BaseModel):
    config: BacktestConfig
    metrics: PerformanceMetrics
    equity_curve: list[EquityPoint]
    trades: list[BacktestTrade]
    final_equity: float
    buy_and_hold_return_pct: float
    rows: int
    methodology: str = "Signals at close t; execution at open t+1; fees/slippage included; stop-first for ambiguous bars. Historical simulation is not a guarantee of future returns."


def chronological_split(frame: pd.DataFrame, train_fraction: float = 0.7) -> tuple[pd.DataFrame, pd.DataFrame]:
    if not 0 < train_fraction < 1:
        raise ValueError("train_fraction must be between 0 and 1")
    if len(frame) < 3:
        raise ValueError("At least three rows are required")
    index = min(len(frame) - 1, max(1, int(len(frame) * train_fraction)))
    return frame.iloc[:index].copy(), frame.iloc[index:].copy()


def run_ema_crossover_backtest(frame: pd.DataFrame, config: BacktestConfig | None = None) -> BacktestResult:
    config = config or BacktestConfig()
    if len(frame) < config.slow_ema + 20:
        raise ValueError("Insufficient chronological OHLCV data for backtest")
    data = add_indicators(frame.copy())
    # Configurable EMAs override the default indicator columns.
    data["fast"] = data.close.ewm(span=config.fast_ema, adjust=False, min_periods=config.fast_ema).mean()
    data["slow"] = data.close.ewm(span=config.slow_ema, adjust=False, min_periods=config.slow_ema).mean()
    cash = config.initial_equity
    position: dict[str, Any] | None = None
    pending: dict[str, Any] | None = None
    trades: list[BacktestTrade] = []
    equity_values: list[float] = []
    timestamps: list[datetime] = []
    fee_rate = config.fee_bps / 10_000
    slippage_rate = config.slippage_bps / 10_000

    def account_equity(mark: float) -> float:
        if position is None:
            return cash
        return cash + position["sign"] * position["quantity"] * mark

    for i in range(1, len(data)):
        bar = data.iloc[i]
        timestamp = data.index[i].to_pydatetime()
        # Open-price entries happen before intrabar protective exits. If an older
        # position is still open at the open, the pending reversal is discarded;
        # a later same-bar exit cannot retroactively enable an open-price fill.
        if pending is not None:
            if position is None and i < len(data) - 1:
                sign = pending["sign"]
                entry_price = float(bar.open) * (1 + sign * slippage_rate)
                atr_at_signal = pending["atr"]
                stop_distance = max(atr_at_signal * config.atr_stop_multiple, entry_price * 0.0001)
                target_distance = max(atr_at_signal * config.atr_target_multiple, stop_distance * 0.1)
                equity_before = cash
                adjusted_unit_risk = stop_distance + entry_price * (fee_rate + slippage_rate)
                quantity = equity_before * config.risk_per_trade_pct / adjusted_unit_risk
                quantity = min(quantity, equity_before * config.max_position_notional_pct / entry_price)
                quantity = min(quantity, cash / (entry_price * (1 + fee_rate)))
                quantity = np.floor(max(0, quantity) / config.lot_size) * config.lot_size
                if quantity > 0:
                    entry_notional = entry_price * quantity
                    entry_fee = entry_notional * fee_rate
                    cash += -sign * entry_notional - entry_fee
                    position = {
                        "sign": sign, "quantity": float(quantity), "entry_price": entry_price,
                        "entry_notional": entry_notional, "entry_fee": entry_fee,
                        "stop": entry_price - sign * stop_distance, "target": entry_price + sign * target_distance,
                        "signal_timestamp": pending["timestamp"], "entry_timestamp": timestamp,
                    }
            pending = None

        # Protective exits are evaluated after the open, including for a new entry.
        if position is not None:
            exit_reference = None
            exit_reason = ""
            if position["sign"] == 1:
                if bar.low <= position["stop"]:
                    exit_reference, exit_reason = position["stop"], "STOP_LOSS"
                elif bar.high >= position["target"]:
                    exit_reference, exit_reason = position["target"], "TAKE_PROFIT"
            else:
                if bar.high >= position["stop"]:
                    exit_reference, exit_reason = position["stop"], "STOP_LOSS"
                elif bar.low <= position["target"]:
                    exit_reference, exit_reason = position["target"], "TAKE_PROFIT"
            if i == len(data) - 1 and exit_reference is None:
                exit_reference, exit_reason = float(bar.close), "END_OF_DATA"
            if exit_reference is not None:
                exit_price = exit_reference * (1 - position["sign"] * slippage_rate)
                gross_exit = exit_price * position["quantity"]
                exit_fee = gross_exit * fee_rate
                cash += position["sign"] * gross_exit - exit_fee
                pnl = (exit_price - position["entry_price"]) * position["quantity"] * position["sign"] - position["entry_fee"] - exit_fee
                total_fees = position["entry_fee"] + exit_fee
                trades.append(BacktestTrade(
                    side="LONG" if position["sign"] == 1 else "SHORT",
                    signal_timestamp=position["signal_timestamp"], entry_timestamp=position["entry_timestamp"],
                    exit_timestamp=timestamp, entry_price=position["entry_price"], exit_price=exit_price,
                    quantity=position["quantity"], stop_loss=position["stop"], take_profit=position["target"],
                    pnl=pnl, return_pct=pnl / position["entry_notional"] if position["entry_notional"] else 0,
                    exit_reason=exit_reason, fees=total_fees,
                ))
                position = None

        # Form a new signal at this close for the next bar; no same-bar fill.
        previous = data.iloc[i - 1]
        if pd.notna(previous.fast) and pd.notna(previous.slow) and pd.notna(bar.fast) and pd.notna(bar.slow) and pd.notna(bar.atr_14):
            crossed_up = previous.fast <= previous.slow and bar.fast > bar.slow
            crossed_down = previous.fast >= previous.slow and bar.fast < bar.slow
            if crossed_up or (crossed_down and config.allow_short):
                pending = {"sign": 1 if crossed_up else -1, "atr": float(bar.atr_14), "timestamp": timestamp}
        timestamps.append(timestamp)
        equity_values.append(float(account_equity(float(bar.close))))

    curve = pd.Series(equity_values, index=pd.DatetimeIndex(timestamps), dtype=float)
    drawdowns = drawdown_series(curve)
    returns = curve.pct_change().dropna()
    stats = trade_statistics([trade.pnl for trade in trades])
    buy_hold = config.initial_equity * data.close.iloc[1:].astype(float) / float(data.close.iloc[0])
    buy_hold.index = curve.index
    points = [
        EquityPoint(timestamp=timestamp.to_pydatetime(), equity=float(equity), drawdown=float(drawdowns.loc[timestamp]), buy_and_hold=float(buy_hold.loc[timestamp]))
        for timestamp, equity in curve.items()
    ]
    final_equity = float(curve.iloc[-1])
    metrics = PerformanceMetrics(
        total_return_pct=(final_equity / config.initial_equity - 1) * 100,
        sharpe_ratio=sharpe_ratio(returns, periods_per_year=config.periods_per_year),
        sortino_ratio=sortino_ratio(returns, periods_per_year=config.periods_per_year),
        max_drawdown_pct=float(abs(drawdowns.min()) * 100) if len(drawdowns) else 0,
        annualized_volatility_pct=annualized_volatility(returns, config.periods_per_year) * 100,
        win_rate=stats["win_rate"], profit_factor=stats["profit_factor"], expectancy=stats["expectancy"],
        average_win=stats["average_win"], average_loss=stats["average_loss"], trade_count=int(stats["trade_count"]),
    )
    return BacktestResult(
        config=config, metrics=metrics, equity_curve=points, trades=trades, final_equity=final_equity,
        buy_and_hold_return_pct=(float(buy_hold.iloc[-1]) / config.initial_equity - 1) * 100,
        rows=len(data),
    )
