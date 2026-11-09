"""Deterministic risk-based position sizing and capital allocation."""
from __future__ import annotations

import math

from agents.base import BaseAgent
from config.settings import RiskConfig
from models.agent_outputs import MoneyManagerOutput, TraceSpan
from models.portfolio import PortfolioSnapshot
from models.trade import TradeProposal


class MoneyManager(BaseAgent):
    name = "Money Manager"

    def __init__(self, config: RiskConfig):
        self.config = config

    def size(self, proposal: TradeProposal, portfolio: PortfolioSnapshot, *, span: TraceSpan) -> MoneyManagerOutput:
        with span.tool("calculate_position_size", f"equity={portfolio.equity:.2f}, entry={proposal.entry_price}, stop={proposal.stop_loss}") as call:
            equity = portfolio.equity
            available_risk_pct = max(0.0, min(
                self.config.max_risk_per_trade_pct,
                self.config.max_portfolio_risk_pct - portfolio.portfolio_risk_pct,
            ))
            risk_amount = equity * available_risk_pct
            risk_per_unit = proposal.risk_per_unit
            fee_rate = self.config.fee_bps / 10_000
            slippage_rate = self.config.slippage_bps / 10_000
            adjusted_risk_per_unit = risk_per_unit + proposal.entry_price * (fee_rate + slippage_rate)
            constraints: list[str] = ["Equity × permitted risk percentage", "Stop distance + estimated fees/slippage"]
            raw_quantity = risk_amount / adjusted_risk_per_unit if adjusted_risk_per_unit > 0 else 0.0
            capped = raw_quantity
            buying_power_cap = portfolio.buying_power / (proposal.entry_price * (1 + fee_rate + slippage_rate)) if proposal.entry_price > 0 else 0
            if buying_power_cap < capped:
                constraints.append("Available buying-power cap")
            capped = min(capped, buying_power_cap)
            position_cap = equity * self.config.max_position_notional_pct / proposal.entry_price
            if position_cap < capped:
                constraints.append("Maximum position-notional cap")
            capped = min(capped, position_cap)
            exposure_cap = max(0.0, (self.config.max_gross_exposure_pct - portfolio.gross_exposure_pct) * equity / proposal.entry_price)
            if exposure_cap < capped:
                constraints.append("Remaining gross-exposure cap")
            capped = min(capped, exposure_cap)
            lot = self.config.lot_size
            quantity = math.floor(max(0.0, capped) / lot) * lot
            quantity = round(quantity, 8)
            notional = quantity * proposal.entry_price
            estimated_fees = notional * fee_rate
            estimated_slippage = notional * slippage_rate
            decision = "APPROVED" if quantity > 0 and notional + estimated_fees <= portfolio.buying_power + 1e-8 else "REJECTED"
            explanation = (
                f"Raw quantity {raw_quantity:.6f} = risk amount {risk_amount:.2f} / adjusted unit risk "
                f"{adjusted_risk_per_unit:.6f}; final {quantity:g} after buying-power, notional, exposure, and {lot:g}-unit lot rounding."
            )
            if decision == "REJECTED":
                explanation += " No positive executable quantity remains within capital limits."
            call.output_summary = f"{decision}: quantity={quantity:g}, notional={notional:.2f}"
        return MoneyManagerOutput(
            decision=decision,
            quantity=quantity,
            risk_amount=round(risk_amount, 4),
            risk_per_unit=round(risk_per_unit, 8),
            estimated_fees=round(estimated_fees, 4),
            estimated_slippage=round(estimated_slippage, 4),
            notional=round(notional, 4),
            buying_power=round(portfolio.buying_power, 4),
            constraints_applied=constraints,
            explanation=explanation,
        )
