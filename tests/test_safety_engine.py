from datetime import datetime, timedelta, timezone

import pytest

from config.settings import get_risk_config
from database.db import Database
from database.repository import Repository
from execution.safety_engine import DeterministicSafetyEngine
from models.agent_outputs import MarketAnalysisOutput, MoneyManagerOutput, RiskManagerOutput, RulesAuditOutput, SupervisorOutput
from models.trade import Side, TradeProposal


def fixtures(tmp_path, **proposal_changes):
    repo = Repository(Database(f"sqlite:///{tmp_path / 'safety.db'}"), get_risk_config())
    values = dict(run_id="r", symbol="TEST", side=Side.LONG, entry_price=100, stop_loss=98, take_profit=104, quantity=10, timeframe="1d", market_timestamp=datetime.now(timezone.utc), client_order_id="unique")
    values.update(proposal_changes)
    proposal = TradeProposal(**values)
    market = MarketAnalysisOutput(market_regime="BULLISH", direction="LONG", confidence=0.8, entry_zone=None, stop_loss=98, take_profit=104, supporting_evidence=[], conflicting_evidence=[], data_timestamp=proposal.market_timestamp.isoformat())
    rules = RulesAuditOutput(decision="PASS", rules_checked=[], violations=[], evidence=[], explanation="test")
    risk = RiskManagerOutput(decision="APPROVED", risk_percentage=0.01, maximum_permitted_loss=1000, risk_reward_ratio=2, portfolio_exposure=0, portfolio_risk=0, violated_restrictions=[], explanation="test")
    money = MoneyManagerOutput(decision="APPROVED", quantity=proposal.quantity, risk_amount=1000, risk_per_unit=2, estimated_fees=0.1, estimated_slippage=0.2, notional=1000, buying_power=100000, constraints_applied=[], explanation="test")
    supervisor = SupervisorOutput(decision="APPROVED", concerns=[], missing_information=[], disagreements=[], explanation="test")
    return DeterministicSafetyEngine(repo, get_risk_config()), proposal, market, rules, risk, money, supervisor


def test_safety_accepts_valid_complete_proposal(tmp_path):
    engine, proposal, *outputs = fixtures(tmp_path)
    result = engine.validate(proposal, *outputs)
    assert result.approved, result.violations
    assert all(result.checks.values())


def test_safety_rejects_incomplete_agent_outputs(tmp_path):
    engine, proposal, *outputs = fixtures(tmp_path)
    result = engine.validate(proposal, outputs[0], None, *outputs[2:])
    assert not result.approved
    assert not result.checks["required_agent_outputs"]


def test_safety_rejects_stale_market_data(tmp_path):
    engine, proposal, *outputs = fixtures(tmp_path, market_timestamp=datetime.now(timezone.utc) - timedelta(days=10))
    result = engine.validate(proposal, *outputs)
    assert not result.approved
    assert not result.checks["market_data_freshness"]


def test_safety_rejects_invalid_quantity_and_conflicting_outputs(tmp_path):
    engine, proposal, market, rules, risk, money, supervisor = fixtures(tmp_path, quantity=20)
    money = money.model_copy(update={"quantity": 10})
    result = engine.validate(proposal, market, rules, risk, money, supervisor)
    assert not result.approved
    assert not result.checks["valid_quantity"]


def test_safety_rechecks_risk_even_if_agent_approved(tmp_path):
    engine, proposal, market, rules, risk, money, supervisor = fixtures(tmp_path, quantity=1000)
    money = money.model_copy(update={"quantity": 1000, "notional": 100000})
    result = engine.validate(proposal, market, rules, risk, money, supervisor)
    assert not result.approved
    assert not result.checks["trade_risk"]
