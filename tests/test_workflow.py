from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

from agents.orchestrator import QuantPilotOrchestrator
from config.settings import Settings, get_risk_config
from models.trade import FinalOutcome, ResearchRequest
from tools.market_data import MarketDataError, MarketDataService


class StaticProvider:
    name = "static-test"
    is_synthetic = False

    def __init__(self, frame):
        self.frame = frame

    def history(self, symbol, timeframe, rows=300):
        return self.frame.copy()


class FailingProvider:
    name = "failure"
    is_synthetic = False

    def history(self, symbol, timeframe, rows=300):
        raise MarketDataError("deterministic test outage")


def bullish_cross_frame():
    rows = 260
    close = np.linspace(50, 120, rows)
    close[-6:] = close[-6] - np.array([0, 1.6, 3.2, 4.8, 6.4, 8.0])
    close[-1] = close[-2] + 6
    index = pd.date_range(end=pd.Timestamp.now(tz="UTC").floor("D"), periods=rows, freq="D")
    return pd.DataFrame({
        "open": np.r_[close[0], close[:-1]],
        "high": np.maximum(np.r_[close[0], close[:-1]], close) + 1,
        "low": np.minimum(np.r_[close[0], close[:-1]], close) - 1,
        "close": close, "volume": np.r_[np.full(rows - 1, 1000.0), 2000.0],
    }, index=index)


def orchestrator(tmp_path, provider):
    settings = Settings(database_url=f"sqlite:///{tmp_path / 'workflow.db'}", data_provider="synthetic")
    return QuantPilotOrchestrator(settings, market_data=MarketDataService(provider=provider, max_data_age=get_risk_config().max_data_age_minutes))


def test_failed_agent_or_market_data_never_becomes_approval(tmp_path):
    app = orchestrator(tmp_path, FailingProvider())
    report = app.run(ResearchRequest(ticker="TEST", timeframe="1d"))
    assert report.outcome == FinalOutcome.REJECTED
    assert "Market-data stage failed" in report.reasons[-1]
    assert report.execution is None
    assert app.repository.get_run(report.run_id) is not None


def test_failed_agent_execution_is_traced_and_fail_closed(tmp_path):
    app = orchestrator(tmp_path, StaticProvider(bullish_cross_frame()))

    def fail(*args, **kwargs):
        raise RuntimeError("deterministic agent crash")

    app.workflow.market_analyst.analyze = fail
    report = app.run(ResearchRequest(ticker="TEST", timeframe="1d"))
    assert report.outcome == FinalOutcome.REJECTED
    assert "Required analysis agent failed" in report.reasons[-1]
    failed = [trace for trace in report.traces if trace.agent == "Market Analyst"]
    assert failed and failed[0].status == "FAILED"
    assert report.execution is None


def test_complete_deterministic_workflow_executes_paper_trade(tmp_path):
    app = orchestrator(tmp_path, StaticProvider(bullish_cross_frame()))
    report = app.run(ResearchRequest(ticker="TEST", timeframe="1d", auto_execute=True))
    assert report.outcome == FinalOutcome.APPROVED, report.reasons
    assert report.rules.decision == "PASS"
    assert report.risk.decision == "APPROVED"
    assert report.money.quantity > 0
    assert report.supervisor.decision == "APPROVED"
    assert report.safety.approved
    assert report.execution.executed
    assert len(app.repository.positions()) == 1
    assert all(trace.status != "FAILED" for trace in report.traces)
    assert app.repository.get_run(report.run_id)["outcome"] == "APPROVED"


def test_streaming_workflow_emits_node_progress_and_final_report(tmp_path):
    app = orchestrator(tmp_path, StaticProvider(bullish_cross_frame()))
    updates = list(app.workflow.stream(ResearchRequest(ticker="TEST", timeframe="1d", auto_execute=False)))
    nodes = [node for update in updates for node in update]
    assert "parallel_analysis" in nodes
    assert "safety_validation" in nodes
    assert nodes[-1] == "final_report"
    report = updates[-1]["final_report"]["report"]
    assert report.outcome == FinalOutcome.APPROVED
    assert report.execution.executed is False


def test_no_trade_outcome_for_sideways_market(tmp_path, flat_ohlcv):
    flat_ohlcv.index = pd.date_range(end=pd.Timestamp.now(tz="UTC").floor("D"), periods=len(flat_ohlcv), freq="D")
    app = orchestrator(tmp_path, StaticProvider(flat_ohlcv))
    report = app.run(ResearchRequest(ticker="FLAT", timeframe="1d", auto_execute=False))
    assert report.outcome == FinalOutcome.NO_TRADE
    assert report.market.direction == "NONE"
    assert report.execution is None
