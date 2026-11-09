from datetime import datetime, timezone

import pytest

from agents.money_manager import MoneyManager
from agents.risk_manager import RiskManager
from config.settings import RiskConfig, get_risk_config
from models.agent_outputs import MarketAnalysisOutput, TraceSpan
from models.portfolio import PortfolioSnapshot
from models.trade import Side, TradeProposal


def proposal(**kwargs):
    values = dict(run_id="r", symbol="TEST", side=Side.LONG, entry_price=100.0, stop_loss=98.0, take_profit=104.0, timeframe="1d", market_timestamp=datetime.now(timezone.utc), client_order_id="client-1")
    values.update(kwargs)
    return TradeProposal(**values)


def market(atr=1.0):
    return MarketAnalysisOutput(market_regime="BULLISH", direction="LONG", confidence=0.8, entry_zone=None, stop_loss=98, take_profit=104, supporting_evidence=[], conflicting_evidence=[], data_timestamp="2024-01-01T00:00:00Z", features={"atr_14": atr, "close": 100})


def portfolio(**kwargs):
    values = dict(equity=100_000, cash=100_000, buying_power=100_000)
    values.update(kwargs)
    return PortfolioSnapshot(**values)


def test_position_sizing_accounts_for_costs_and_lot_rounding():
    result = MoneyManager(get_risk_config()).size(proposal(), portfolio(), span=TraceSpan("test"))
    # Raw risk-based quantity is below 500 because costs are included.
    assert 0 < result.quantity < 500
    assert result.decision == "APPROVED"
    assert result.notional <= 25_000
    assert result.estimated_fees > 0
    assert result.estimated_slippage > 0


def test_position_sizing_respects_buying_power():
    result = MoneyManager(get_risk_config()).size(proposal(), portfolio(equity=1000, cash=100, buying_power=100), span=TraceSpan("test"))
    assert result.notional + result.estimated_fees <= 100.000001


def test_zero_capital_rejects_position_size():
    result = MoneyManager(get_risk_config()).size(proposal(), portfolio(equity=0, cash=0, buying_power=0), span=TraceSpan("test"))
    assert result.quantity == 0
    assert result.decision == "REJECTED"


def test_invalid_stop_is_rejected_by_risk_manager():
    invalid = TradeProposal.model_construct(**{**proposal().model_dump(), "stop_loss": 101.0})
    result = RiskManager(get_risk_config()).evaluate(invalid, market(), portfolio(), span=TraceSpan("test"))
    assert result.decision == "REJECTED"
    assert any("stop-loss" in item for item in result.violated_restrictions)


def test_minimum_risk_reward_is_enforced():
    result = RiskManager(get_risk_config()).evaluate(proposal(take_profit=101), market(), portfolio(), span=TraceSpan("test"))
    assert result.decision == "REJECTED"
    assert any("Risk/reward" in item for item in result.violated_restrictions)


def test_daily_loss_limit_vetoes_trade():
    result = RiskManager(get_risk_config()).evaluate(proposal(), market(), portfolio(daily_pnl=-2000, day_start_equity=100000), span=TraceSpan("test"))
    assert result.decision == "REJECTED"
    assert any("Daily loss" in item for item in result.violated_restrictions)


def test_maximum_drawdown_vetoes_trade():
    result = RiskManager(get_risk_config()).evaluate(proposal(), market(), portfolio(drawdown_pct=0.05), span=TraceSpan("test"))
    assert result.decision == "REJECTED"
    assert any("Drawdown" in item for item in result.violated_restrictions)


def test_abnormal_volatility_vetoes_trade():
    result = RiskManager(get_risk_config()).evaluate(proposal(), market(atr=20), portfolio(), span=TraceSpan("test"))
    assert result.decision == "REJECTED"
    assert any("volatility" in item.lower() for item in result.violated_restrictions)
