"""Portfolio snapshots and performance-response models."""
from __future__ import annotations

from datetime import date, datetime, timezone

from pydantic import BaseModel, Field

from models.trade import Position


class PortfolioSnapshot(BaseModel):
    equity: float
    cash: float
    buying_power: float
    initial_equity: float = 100_000.0
    day_start_equity: float = 100_000.0
    realized_pnl: float = 0.0
    daily_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    high_water_mark: float = 100_000.0
    drawdown_pct: float = 0.0
    gross_exposure_pct: float = 0.0
    portfolio_risk_pct: float = 0.0
    open_positions: list[Position] = Field(default_factory=list)
    trading_halted: bool = False
    halt_reasons: list[str] = Field(default_factory=list)
    as_of: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def daily_loss_pct(self) -> float:
        return max(0.0, -self.daily_pnl / self.day_start_equity) if self.day_start_equity > 0 else 0.0


class PerformanceMetrics(BaseModel):
    total_return_pct: float
    sharpe_ratio: float
    sortino_ratio: float
    max_drawdown_pct: float
    annualized_volatility_pct: float
    win_rate: float
    profit_factor: float | None
    expectancy: float
    average_win: float
    average_loss: float
    trade_count: int
