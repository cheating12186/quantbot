"""Portfolio monitoring, exposure calculation, and automatic hard-limit halts."""
from __future__ import annotations

from agents.base import BaseAgent
from database.repository import Repository
from execution.paper_broker import PaperBroker
from models.agent_outputs import TraceSpan
from models.portfolio import PortfolioSnapshot


class PortfolioMonitor(BaseAgent):
    name = "Portfolio Monitor"

    def __init__(self, repository: Repository, broker: PaperBroker):
        self.repository = repository
        self.broker = broker

    def review(self, *, span: TraceSpan) -> PortfolioSnapshot:
        with span.tool("refresh_portfolio_risk", "SQLite account and open positions") as call:
            snapshot = self.repository.snapshot()
            call.output_summary = f"equity={snapshot.equity:.2f}, drawdown={snapshot.drawdown_pct:.2%}, halted={snapshot.trading_halted}"
        return snapshot

    def process_candle(self, symbol: str, open_: float, high: float, low: float, close: float):
        return self.broker.process_candle(symbol, open_, high, low, close)
