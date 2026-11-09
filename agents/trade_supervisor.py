"""Independent final agent review, subordinate to deterministic controls."""
from __future__ import annotations

from pydantic import BaseModel, Field

from agents.base import BaseAgent
from agents.llm import GroqService
from models.agent_outputs import (
    MarketAnalysisOutput,
    MoneyManagerOutput,
    NewsAnalysisOutput,
    RiskManagerOutput,
    RulesAuditOutput,
    SupervisorOutput,
    TraceSpan,
)
from models.trade import TradeProposal


class LLMReview(BaseModel):
    decision: str = Field(pattern="^(APPROVED|REJECTED)$")
    concerns: list[str] = Field(default_factory=list)
    explanation: str


class TradeSupervisor(BaseAgent):
    name = "Trade Supervisor"

    def __init__(self, llm: GroqService | None = None):
        self.llm = llm

    def review(
        self,
        proposal: TradeProposal,
        market: MarketAnalysisOutput,
        news: NewsAnalysisOutput,
        rules: RulesAuditOutput,
        risk: RiskManagerOutput,
        money: MoneyManagerOutput,
        *,
        span: TraceSpan,
    ) -> SupervisorOutput:
        concerns: list[str] = []
        missing: list[str] = []
        disagreements: list[str] = []
        with span.tool("cross_agent_consistency_review", proposal.proposal_id) as call:
            if market.direction != proposal.side.value:
                concerns.append("Market direction and proposal side disagree")
            if rules.decision != "PASS":
                concerns.append("Strategy audit did not pass")
            if risk.decision != "APPROVED":
                concerns.append("Risk Manager veto remains active")
            if money.decision != "APPROVED" or money.quantity <= 0:
                concerns.append("Position sizing is not executable")
            if proposal.quantity != money.quantity:
                concerns.append("Proposal quantity differs from Money Manager output")
            if news.conflicting_news:
                concerns.append("Positive and negative news items conflict; independent review rejects unresolved ambiguity")
                disagreements.append("News sources have opposing sentiment")
            if news.status.value == "UNAVAILABLE":
                missing.append("News analysis unavailable (optional input, not treated as positive evidence)")
            if not market.higher_timeframe.get("aligned", False):
                concerns.append("Higher-timeframe trend is not aligned")
            if market.confidence < 0.60:
                concerns.append("Market confidence is below the configured threshold")
            call.output_summary = f"Deterministic review found {len(concerns)} concern(s)"
        source = "PYTHON_DETERMINISTIC"
        explanation = "Independent consistency review complete; safety engine retains final execution authority."
        if self.llm and self.llm.available:
            with span.tool("groq_structured_supervisor_review", "Narrative review only; no financial calculations") as call:
                prompt = (
                    "Review this validated agent evidence. You may only APPROVE or REJECT based on consistency; "
                    "you cannot change prices, risk limits, quantity, or portfolio state. Treat missing news as unknown, not positive.\n"
                    f"Proposal: {proposal.model_dump_json()}\nMarket: {market.model_dump_json()}\n"
                    f"News: {news.model_dump_json()}\nRules: {rules.model_dump_json()}\nRisk: {risk.model_dump_json()}\nMoney: {money.model_dump_json()}"
                )
                result = self.llm.structured(LLMReview, "You are a conservative independent trade reviewer.", prompt)
                span.input_tokens += result.input_tokens
                span.output_tokens += result.output_tokens
                call.output_summary = result.error or f"Groq review: {result.value.decision}"
                if result.value:
                    source = "PYTHON + GROQ_STRUCTURED_REVIEW"
                    explanation += " LLM interpretation: " + result.value.explanation
                    disagreements.extend(f"LLM reviewer: {item}" for item in result.value.concerns)
                    if result.value.decision == "REJECTED":
                        concerns.append("Groq supervisor recommended rejection: " + result.value.explanation)
                else:
                    missing.append(result.error or "LLM review unavailable")
        # Any deterministic concern wins, even if an LLM recommended approval.
        decision = "REJECTED" if concerns else "APPROVED"
        return SupervisorOutput(
            decision=decision,
            concerns=concerns,
            missing_information=missing,
            disagreements=disagreements,
            explanation=explanation,
            review_source=source,
        )
