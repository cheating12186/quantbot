"""Independent capital-protection agent with veto authority."""
from __future__ import annotations

from agents.base import BaseAgent
from config.settings import RiskConfig
from models.agent_outputs import MarketAnalysisOutput, RiskManagerOutput, TraceSpan
from models.portfolio import PortfolioSnapshot
from models.trade import Side, TradeProposal


class RiskManager(BaseAgent):
    name = "Risk Manager"

    def __init__(self, config: RiskConfig):
        self.config = config

    def evaluate(self, proposal: TradeProposal, market: MarketAnalysisOutput, portfolio: PortfolioSnapshot, *, span: TraceSpan) -> RiskManagerOutput:
        with span.tool("evaluate_risk_limits", proposal.model_dump_json()) as call:
            violations: list[str] = []
            equity = portfolio.equity
            if equity <= 0:
                violations.append("Account equity must be positive")
            maximum_loss = max(0.0, equity * self.config.max_risk_per_trade_pct)
            rr = proposal.risk_reward
            if rr < self.config.min_risk_reward:
                violations.append(f"Risk/reward {rr:.2f} is below minimum {self.config.min_risk_reward:.2f}")
            if portfolio.trading_halted:
                violations.extend(f"Trading halt: {reason}" for reason in portfolio.halt_reasons)
            daily_loss_pct = max(0.0, -portfolio.daily_pnl / portfolio.day_start_equity) if portfolio.day_start_equity else 0.0
            if daily_loss_pct >= self.config.max_daily_loss_pct:
                violations.append(f"Daily loss {daily_loss_pct:.2%} reached {self.config.max_daily_loss_pct:.2%} limit")
            if portfolio.drawdown_pct >= self.config.max_account_drawdown_pct:
                violations.append(f"Drawdown {portfolio.drawdown_pct:.2%} reached {self.config.max_account_drawdown_pct:.2%} limit")
            if len(portfolio.open_positions) >= self.config.max_concurrent_positions:
                violations.append(f"Maximum concurrent positions ({self.config.max_concurrent_positions}) reached")
            if any(position.symbol == proposal.symbol for position in portfolio.open_positions):
                violations.append(f"An open {proposal.symbol} position already creates concentration")
            if portfolio.portfolio_risk_pct >= self.config.max_portfolio_risk_pct:
                violations.append(f"Portfolio risk {portfolio.portfolio_risk_pct:.2%} reached {self.config.max_portfolio_risk_pct:.2%} limit")
            if portfolio.gross_exposure_pct >= self.config.max_gross_exposure_pct:
                violations.append(f"Gross exposure {portfolio.gross_exposure_pct:.2%} reached limit")
            atr = market.features.get("atr_14")
            close = market.features.get("close")
            if atr and close and atr / close > self.config.max_atr_pct:
                violations.append(f"Abnormal volatility: ATR/price {atr / close:.2%} exceeds {self.config.max_atr_pct:.2%}")
            # Independent geometry checks even though Pydantic validates normal proposals.
            if proposal.side == Side.LONG and proposal.stop_loss >= proposal.entry_price:
                violations.append("LONG stop-loss must be below entry")
            if proposal.side == Side.SHORT and proposal.stop_loss <= proposal.entry_price:
                violations.append("SHORT stop-loss must be above entry")
            portfolio_risk_after = portfolio.portfolio_risk_pct + self.config.max_risk_per_trade_pct
            if portfolio_risk_after > self.config.max_portfolio_risk_pct + 1e-12:
                violations.append(f"Projected portfolio risk {portfolio_risk_after:.2%} exceeds {self.config.max_portfolio_risk_pct:.2%}")
            decision = "REJECTED" if violations else "APPROVED"
            call.output_summary = f"{decision}: {len(violations)} violation(s), R/R={rr:.2f}"
        return RiskManagerOutput(
            decision=decision,
            risk_percentage=self.config.max_risk_per_trade_pct,
            maximum_permitted_loss=round(maximum_loss, 4),
            risk_reward_ratio=round(rr, 4),
            portfolio_exposure=round(portfolio.gross_exposure_pct, 6),
            portfolio_risk=round(portfolio.portfolio_risk_pct, 6),
            violated_restrictions=violations,
            explanation="Risk limits independently evaluated in Python. A rejection is final and cannot be overridden by an LLM or orchestrator.",
        )
