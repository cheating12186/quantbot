"""Strict agent output schemas and observable execution tracing."""
from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Iterator

from pydantic import BaseModel, Field

from models.trade import ExecutionResult, FinalOutcome, TradeProposal


class AgentStatus(str, Enum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    UNAVAILABLE = "UNAVAILABLE"


class EntryZone(BaseModel):
    low: float = Field(gt=0)
    high: float = Field(gt=0)


class MarketAnalysisOutput(BaseModel):
    status: AgentStatus = AgentStatus.SUCCESS
    source: str = "PYTHON_DETERMINISTIC"
    market_regime: str
    direction: str
    confidence: float = Field(ge=0, le=1)
    entry_zone: EntryZone | None
    stop_loss: float | None
    take_profit: float | None
    supporting_evidence: list[str]
    conflicting_evidence: list[str]
    data_timestamp: str
    features: dict[str, float | None] = Field(default_factory=dict)
    confidence_components: dict[str, float] = Field(default_factory=dict)
    higher_timeframe: dict[str, Any] = Field(default_factory=dict)
    data_limitations: list[str] = Field(default_factory=list)
    explanation: str = ""
    llm_interpretation: str | None = None


class NewsItem(BaseModel):
    title: str
    source: str = "unknown"
    url: str = ""
    published_at: datetime | None = None
    sentiment: str = "unknown"
    sentiment_score: float = 0.0


class NewsAnalysisOutput(BaseModel):
    status: AgentStatus
    sentiment: str = "unknown"
    confidence: float = Field(default=0, ge=0, le=1)
    items: list[NewsItem] = Field(default_factory=list)
    conflicting_news: bool = False
    events: list[str] = Field(default_factory=list)
    explanation: str
    source: str = "NONE"


class RuleEvidence(BaseModel):
    rule: str
    passed: bool
    observed: Any
    expected: Any


class RulesAuditOutput(BaseModel):
    status: AgentStatus = AgentStatus.SUCCESS
    decision: str
    rules_checked: list[str]
    violations: list[str]
    evidence: list[RuleEvidence]
    explanation: str
    source: str = "PYTHON_DETERMINISTIC"


class RiskManagerOutput(BaseModel):
    status: AgentStatus = AgentStatus.SUCCESS
    decision: str
    risk_percentage: float
    maximum_permitted_loss: float
    risk_reward_ratio: float
    portfolio_exposure: float
    portfolio_risk: float
    violated_restrictions: list[str]
    explanation: str
    source: str = "PYTHON_DETERMINISTIC"


class MoneyManagerOutput(BaseModel):
    status: AgentStatus = AgentStatus.SUCCESS
    decision: str
    quantity: float
    risk_amount: float
    risk_per_unit: float
    estimated_fees: float
    estimated_slippage: float
    notional: float
    buying_power: float
    constraints_applied: list[str]
    explanation: str
    source: str = "PYTHON_DETERMINISTIC"


class SupervisorOutput(BaseModel):
    status: AgentStatus = AgentStatus.SUCCESS
    decision: str
    concerns: list[str]
    missing_information: list[str]
    disagreements: list[str]
    explanation: str
    review_source: str = "PYTHON_DETERMINISTIC"


class SafetyValidationOutput(BaseModel):
    approved: bool
    violations: list[str]
    checks: dict[str, bool]
    explanation: str
    source: str = "DETERMINISTIC_SAFETY_ENGINE"


class ToolCallTrace(BaseModel):
    tool: str
    status: AgentStatus = AgentStatus.SUCCESS
    started_at: datetime
    duration_ms: float = 0
    input_summary: str = ""
    output_summary: str = ""
    error: str | None = None


class AgentTrace(BaseModel):
    agent: str
    status: AgentStatus
    started_at: datetime
    duration_ms: float
    tool_calls: list[ToolCallTrace] = Field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    error: str | None = None


class TraceSpan:
    def __init__(self, agent: str):
        self.agent = agent
        self.started_at = datetime.now(timezone.utc)
        self._start = time.perf_counter()
        self.status = AgentStatus.SUCCESS
        self.error: str | None = None
        self.tool_calls: list[ToolCallTrace] = []
        self.input_tokens = 0
        self.output_tokens = 0

    @contextmanager
    def tool(self, name: str, input_summary: str = "") -> Iterator[ToolCallTrace]:
        started = datetime.now(timezone.utc)
        start = time.perf_counter()
        call = ToolCallTrace(tool=name, started_at=started, input_summary=input_summary[:500])
        self.tool_calls.append(call)
        try:
            yield call
        except Exception as exc:
            call.status = AgentStatus.FAILED
            call.error = str(exc)
            raise
        finally:
            call.duration_ms = round((time.perf_counter() - start) * 1000, 3)

    def finish(self) -> AgentTrace:
        return AgentTrace(
            agent=self.agent,
            status=self.status,
            started_at=self.started_at,
            duration_ms=round((time.perf_counter() - self._start) * 1000, 3),
            tool_calls=self.tool_calls,
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            error=self.error,
        )


class ExecutionContext:
    """Thread-safe in-memory trace collector persisted after each workflow."""
    def __init__(self):
        self._traces: list[AgentTrace] = []
        self._lock = threading.Lock()

    @contextmanager
    def span(self, agent: str) -> Iterator[TraceSpan]:
        span = TraceSpan(agent)
        try:
            yield span
        except Exception as exc:
            span.status = AgentStatus.FAILED
            span.error = str(exc)
            raise
        finally:
            with self._lock:
                self._traces.append(span.finish())

    @property
    def traces(self) -> list[AgentTrace]:
        with self._lock:
            return list(self._traces)


class FinalReport(BaseModel):
    run_id: str
    outcome: FinalOutcome
    reasons: list[str]
    proposal: TradeProposal | None = None
    market: MarketAnalysisOutput | None = None
    news: NewsAnalysisOutput | None = None
    rules: RulesAuditOutput | None = None
    risk: RiskManagerOutput | None = None
    money: MoneyManagerOutput | None = None
    supervisor: SupervisorOutput | None = None
    safety: SafetyValidationOutput | None = None
    execution: ExecutionResult | None = None
    traces: list[AgentTrace] = Field(default_factory=list)
    data_sources: dict[str, Any] = Field(default_factory=dict)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    disclaimer: str = "Research and simulated paper trading only. Not financial advice; past performance does not guarantee future results."
