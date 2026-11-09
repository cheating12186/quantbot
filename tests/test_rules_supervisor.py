from datetime import datetime, timezone

from agents.rules_auditor import StrategyRulesAuditor
from agents.trade_supervisor import TradeSupervisor
from config.settings import get_strategy_config
from models.agent_outputs import MarketAnalysisOutput, MoneyManagerOutput, NewsAnalysisOutput, RiskManagerOutput, TraceSpan
from models.market import DataQuality, MarketDataset
from models.trade import Side, TradeProposal


def make_dataset(frame):
    return MarketDataset("TEST", "1d", frame, "test", DataQuality(valid=True, rows=len(frame), source="test"), datetime.now(timezone.utc))


def test_strategy_rule_violations_have_numerical_evidence(ohlcv):
    proposal = TradeProposal(run_id="r", symbol="TEST", side=Side.LONG, entry_price=float(ohlcv.close.iloc[-1]), stop_loss=float(ohlcv.close.iloc[-1]) - 2, take_profit=float(ohlcv.close.iloc[-1]) + 4, timeframe="1d", market_timestamp=ohlcv.index[-1].to_pydatetime(), client_order_id="x")
    market = MarketAnalysisOutput(market_regime="BULLISH", direction="LONG", confidence=0.8, entry_zone=None, stop_loss=proposal.stop_loss, take_profit=proposal.take_profit, supporting_evidence=[], conflicting_evidence=[], data_timestamp=proposal.market_timestamp.isoformat(), higher_timeframe={"direction": "LONG", "aligned": True})
    result = StrategyRulesAuditor(get_strategy_config()).audit(proposal, market, make_dataset(ohlcv), span=TraceSpan("test"))
    assert result.decision == "FAIL"  # Fixture does not intentionally create a fresh final-bar cross.
    assert any(item.rule == "Fresh EMA 9/15 crossover" and not item.passed for item in result.evidence)
    assert all(item.observed is not None for item in result.evidence)


def test_conflicting_agent_outputs_force_supervisor_rejection():
    proposal = TradeProposal(run_id="r", symbol="TEST", side=Side.LONG, entry_price=100, stop_loss=98, take_profit=104, quantity=10, timeframe="1d", market_timestamp=datetime.now(timezone.utc), client_order_id="x")
    market = MarketAnalysisOutput(market_regime="BEARISH", direction="SHORT", confidence=0.8, entry_zone=None, stop_loss=98, take_profit=104, supporting_evidence=[], conflicting_evidence=[], data_timestamp="2024-01-01T00:00:00Z", higher_timeframe={"aligned": False})
    from models.agent_outputs import RulesAuditOutput
    rules = RulesAuditOutput(decision="PASS", rules_checked=[], violations=[], evidence=[], explanation="test")
    risk = RiskManagerOutput(decision="APPROVED", risk_percentage=0.01, maximum_permitted_loss=1000, risk_reward_ratio=2, portfolio_exposure=0, portfolio_risk=0, violated_restrictions=[], explanation="test")
    money = MoneyManagerOutput(decision="APPROVED", quantity=10, risk_amount=1000, risk_per_unit=2, estimated_fees=1, estimated_slippage=2, notional=1000, buying_power=100000, constraints_applied=[], explanation="test")
    news = NewsAnalysisOutput(status="SUCCESS", explanation="test")
    result = TradeSupervisor().review(proposal, market, news, rules, risk, money, span=TraceSpan("test"))
    assert result.decision == "REJECTED"
    assert any("disagree" in concern for concern in result.concerns)
