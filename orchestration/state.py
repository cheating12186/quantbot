"""Typed shared state passed through the LangGraph workflow."""
from __future__ import annotations

from typing import TypedDict

from models.agent_outputs import (
    ExecutionContext,
    FinalReport,
    MarketAnalysisOutput,
    MoneyManagerOutput,
    NewsAnalysisOutput,
    RiskManagerOutput,
    RulesAuditOutput,
    SafetyValidationOutput,
    SupervisorOutput,
)
from models.market import MarketDataset
from models.portfolio import PortfolioSnapshot
from models.trade import ExecutionResult, FinalOutcome, ResearchRequest, TradeProposal


class WorkflowState(TypedDict, total=False):
    run_id: str
    request: ResearchRequest
    context: ExecutionContext
    primary_data: MarketDataset
    higher_data: MarketDataset | None
    market: MarketAnalysisOutput
    news: NewsAnalysisOutput
    proposal: TradeProposal
    portfolio: PortfolioSnapshot
    rules: RulesAuditOutput
    risk: RiskManagerOutput
    money: MoneyManagerOutput
    supervisor: SupervisorOutput
    safety: SafetyValidationOutput
    execution: ExecutionResult
    outcome: FinalOutcome
    reasons: list[str]
    fatal_error: str
    report: FinalReport
