"""Final non-LLM gate. Every required approval and numerical limit is rechecked."""
from __future__ import annotations

from datetime import datetime, timezone

from config.settings import RiskConfig
from database.repository import Repository
from models.agent_outputs import (
    MarketAnalysisOutput,
    MoneyManagerOutput,
    RiskManagerOutput,
    RulesAuditOutput,
    SafetyValidationOutput,
    SupervisorOutput,
)
from models.trade import Side, TradeProposal


class DeterministicSafetyEngine:
    def __init__(self, repository: Repository, config: RiskConfig):
        self.repository = repository
        self.config = config

    def validate(
        self,
        proposal: TradeProposal,
        market: MarketAnalysisOutput | None,
        rules: RulesAuditOutput | None,
        risk: RiskManagerOutput | None,
        money: MoneyManagerOutput | None,
        supervisor: SupervisorOutput | None,
        *,
        now: datetime | None = None,
    ) -> SafetyValidationOutput:
        checks: dict[str, bool] = {}
        violations: list[str] = []

        def check(name: str, passed: bool, message: str):
            checks[name] = bool(passed)
            if not passed:
                violations.append(message)

        check("required_agent_outputs", all(value is not None for value in (market, rules, risk, money, supervisor)), "One or more required agent outputs are missing")
        if not all(value is not None for value in (market, rules, risk, money, supervisor)):
            return SafetyValidationOutput(approved=False, violations=violations, checks=checks, explanation="Execution blocked: incomplete agent outputs")
        check("strategy_approval", rules.decision == "PASS", "Strategy audit did not pass")
        check("risk_approval", risk.decision == "APPROVED", "Risk Manager approval is missing")
        check("money_approval", money.decision == "APPROVED", "Money Manager approval is missing")
        check("supervisor_approval", supervisor.decision == "APPROVED", "Trade Supervisor approval is missing")
        check("market_direction", market.direction == proposal.side.value, "Market direction changed or disagrees with proposal")
        check("valid_quantity", proposal.quantity > 0 and proposal.quantity == money.quantity, "Quantity is invalid or differs from approved sizing")
        geometry = proposal.stop_loss < proposal.entry_price < proposal.take_profit if proposal.side == Side.LONG else proposal.take_profit < proposal.entry_price < proposal.stop_loss
        check("price_geometry", geometry, "Entry, stop-loss, and target are directionally invalid")
        check("risk_reward", proposal.risk_reward >= self.config.min_risk_reward, "Risk/reward is below policy")
        portfolio = self.repository.snapshot(now=now)
        check("positive_equity", portfolio.equity > 0, "Account equity is not positive")
        notional = proposal.entry_price * proposal.quantity
        estimated_cost = notional * (1 + (self.config.fee_bps + self.config.slippage_bps) / 10_000)
        check("buying_power", estimated_cost <= portfolio.buying_power + 1e-6, "Estimated cost exceeds buying power")
        actual_risk = proposal.risk_per_unit * proposal.quantity + notional * (self.config.fee_bps + self.config.slippage_bps) / 10_000
        check("trade_risk", actual_risk <= portfolio.equity * self.config.max_risk_per_trade_pct + 1e-5, "Sized trade exceeds maximum risk per trade")
        projected_portfolio_risk = portfolio.portfolio_risk_pct + (proposal.risk_per_unit * proposal.quantity / portfolio.equity if portfolio.equity else 1)
        check("portfolio_risk", projected_portfolio_risk <= self.config.max_portfolio_risk_pct + 1e-8, "Portfolio risk limit would be breached")
        check("position_count", len(portfolio.open_positions) < self.config.max_concurrent_positions, "Maximum concurrent positions reached")
        check("concentration", not any(position.symbol == proposal.symbol for position in portfolio.open_positions), "Symbol already has an open position")
        check("position_notional", notional <= portfolio.equity * self.config.max_position_notional_pct + 1e-6, "Position notional cap exceeded")
        check("daily_loss", portfolio.daily_pnl > -self.config.max_daily_loss_pct * portfolio.day_start_equity, "Daily loss limit breached")
        check("drawdown", portfolio.drawdown_pct < self.config.max_account_drawdown_pct, "Maximum drawdown limit breached")
        check("trading_halt", not portfolio.trading_halted, "Portfolio trading halt is active")
        timestamp = proposal.market_timestamp
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        reference = now or datetime.now(timezone.utc)
        if reference.tzinfo is None:
            reference = reference.replace(tzinfo=timezone.utc)
        age_minutes = (reference - timestamp).total_seconds() / 60
        max_age = self.config.max_data_age_minutes.get(proposal.timeframe, 60)
        check("market_data_freshness", 0 <= age_minutes <= max_age, f"Market data is stale or future-dated ({age_minutes:.1f} minutes; max {max_age})")
        duplicate = any(order.client_order_id == proposal.client_order_id and order.status.value not in ("CANCELLED", "REJECTED") for order in self.repository.orders())
        check("duplicate_order", not duplicate, "Duplicate client order identifier")
        approved = not violations
        return SafetyValidationOutput(
            approved=approved,
            violations=violations,
            checks=checks,
            explanation="All deterministic safety checks passed; paper execution permitted." if approved else "Execution blocked by deterministic safety checks.",
        )
