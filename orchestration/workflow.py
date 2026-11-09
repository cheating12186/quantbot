"""Fail-closed multi-agent trading workflow."""
from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from datetime import datetime, timezone
from typing import Any

from agents.market_analyst import MarketAnalyst
from agents.money_manager import MoneyManager
from agents.news_analyst import NewsSentimentAnalyst
from agents.portfolio_monitor import PortfolioMonitor
from agents.risk_manager import RiskManager
from agents.rules_auditor import StrategyRulesAuditor
from agents.trade_supervisor import TradeSupervisor
from config.settings import StrategyConfig
from database.repository import Repository
from execution.order_manager import OrderManager
from execution.safety_engine import DeterministicSafetyEngine
from models.agent_outputs import ExecutionContext, FinalReport
from models.trade import ExecutionResult, FinalOutcome, ResearchRequest, Side, TradeProposal
from orchestration.state import WorkflowState
from tools.market_data import MarketDataService


class TradingWorkflow:
    def __init__(
        self,
        *,
        market_data: MarketDataService,
        market_analyst: MarketAnalyst,
        news_analyst: NewsSentimentAnalyst,
        rules_auditor: StrategyRulesAuditor,
        risk_manager: RiskManager,
        money_manager: MoneyManager,
        supervisor: TradeSupervisor,
        portfolio_monitor: PortfolioMonitor,
        safety_engine: DeterministicSafetyEngine,
        order_manager: OrderManager,
        repository: Repository,
        strategy: StrategyConfig,
    ):
        self.market_data = market_data
        self.market_analyst = market_analyst
        self.news_analyst = news_analyst
        self.rules_auditor = rules_auditor
        self.risk_manager = risk_manager
        self.money_manager = money_manager
        self.supervisor = supervisor
        self.portfolio_monitor = portfolio_monitor
        self.safety_engine = safety_engine
        self.order_manager = order_manager
        self.repository = repository
        self.strategy = strategy
        self.graph = self._build_graph()

    def _build_graph(self):
        from langgraph.graph import END, START, StateGraph
        builder = StateGraph(WorkflowState)
        builder.add_node("validate_input", self.validate_input)
        builder.add_node("fetch_market_data", self.fetch_market_data)
        builder.add_node("parallel_analysis", self.parallel_analysis)
        builder.add_node("create_proposal", self.create_proposal)
        builder.add_node("strategy_audit", self.strategy_audit)
        builder.add_node("risk_review", self.risk_review)
        builder.add_node("position_sizing", self.position_sizing)
        builder.add_node("supervisor_review", self.supervisor_review)
        builder.add_node("safety_validation", self.safety_validation)
        builder.add_node("paper_execution", self.paper_execution)
        builder.add_node("final_report", self.final_report)
        builder.add_edge(START, "validate_input")
        builder.add_edge("validate_input", "fetch_market_data")
        builder.add_conditional_edges("fetch_market_data", self.route_failure, {"continue": "parallel_analysis", "report": "final_report"})
        builder.add_conditional_edges("parallel_analysis", self.route_failure, {"continue": "create_proposal", "report": "final_report"})
        builder.add_conditional_edges("create_proposal", self.route_opportunity, {"continue": "strategy_audit", "report": "final_report"})
        builder.add_conditional_edges("strategy_audit", self.route_stage, {"continue": "risk_review", "report": "final_report"})
        builder.add_conditional_edges("risk_review", self.route_stage, {"continue": "position_sizing", "report": "final_report"})
        builder.add_conditional_edges("position_sizing", self.route_stage, {"continue": "supervisor_review", "report": "final_report"})
        builder.add_conditional_edges("supervisor_review", self.route_stage, {"continue": "safety_validation", "report": "final_report"})
        builder.add_conditional_edges("safety_validation", self.route_stage, {"continue": "paper_execution", "report": "final_report"})
        builder.add_edge("paper_execution", "final_report")
        builder.add_edge("final_report", END)
        return builder.compile()

    @staticmethod
    def route_failure(state: WorkflowState) -> str:
        return "report" if state.get("fatal_error") else "continue"

    @staticmethod
    def route_opportunity(state: WorkflowState) -> str:
        return "report" if state.get("fatal_error") or state.get("outcome") else "continue"

    @staticmethod
    def route_stage(state: WorkflowState) -> str:
        return "report" if state.get("fatal_error") or state.get("outcome") == FinalOutcome.REJECTED else "continue"

    def validate_input(self, state: WorkflowState) -> dict[str, Any]:
        with state["context"].span("Orchestrator") as span:
            with span.tool("validate_research_request", state["request"].model_dump_json()) as call:
                request = state["request"]
                call.output_summary = f"Validated {request.ticker} {request.timeframe}; PAPER_ONLY=True"
        return {}

    def fetch_market_data(self, state: WorkflowState) -> dict[str, Any]:
        request = state["request"]
        try:
            with state["context"].span("Orchestrator") as span:
                with span.tool("fetch_multi_timeframe_ohlcv", f"{request.ticker} {request.timeframe}") as call:
                    higher_timeframe = self.strategy.higher_timeframe.get(request.timeframe)
                    with ThreadPoolExecutor(max_workers=2) as pool:
                        primary_future = pool.submit(self.market_data.fetch, request.ticker, request.timeframe, request.rows)
                        higher_future = pool.submit(self.market_data.fetch, request.ticker, higher_timeframe, request.rows) if higher_timeframe and higher_timeframe != request.timeframe else None
                        primary = primary_future.result(timeout=45)
                        higher = higher_future.result(timeout=45) if higher_future else primary
                    call.output_summary = f"Primary: {primary.source}/{len(primary.frame)} bars; HTF: {higher.source}/{len(higher.frame)} bars"
            return {"primary_data": primary, "higher_data": higher}
        except Exception as exc:
            return {"fatal_error": f"Market-data stage failed: {exc}", "outcome": FinalOutcome.REJECTED, "reasons": [str(exc)]}

    def parallel_analysis(self, state: WorkflowState) -> dict[str, Any]:
        try:
            with ThreadPoolExecutor(max_workers=2) as pool:
                market_future = pool.submit(self.market_analyst.execute, state["context"], self.market_analyst.analyze, state["primary_data"], state.get("higher_data"))
                news_future = pool.submit(self.news_analyst.execute, state["context"], self.news_analyst.analyze, state["request"].ticker)
                market = market_future.result(timeout=35)
                news = news_future.result(timeout=35)
            return {"market": market, "news": news}
        except FutureTimeout:
            return {"fatal_error": "Parallel agent analysis timed out", "outcome": FinalOutcome.REJECTED, "reasons": ["Agent timeout; no approval inferred"]}
        except Exception as exc:
            return {"fatal_error": f"Required analysis agent failed: {exc}", "outcome": FinalOutcome.REJECTED, "reasons": [str(exc)]}

    def create_proposal(self, state: WorkflowState) -> dict[str, Any]:
        market = state["market"]
        reasons: list[str] = []
        if market.direction == "NONE":
            return {"outcome": FinalOutcome.NO_TRADE, "reasons": ["No sufficiently strong directional opportunity: market evidence score is below threshold"]}
        if market.confidence < self.strategy.min_market_confidence:
            return {"outcome": FinalOutcome.NO_TRADE, "reasons": [f"Confidence {market.confidence:.2f} is below {self.strategy.min_market_confidence:.2f}"]}
        if market.stop_loss is None or market.take_profit is None or market.features.get("close") is None:
            return {"fatal_error": "Market Analyst returned incomplete trade levels", "outcome": FinalOutcome.REJECTED, "reasons": ["Incomplete market output"]}
        run_id = state["run_id"]
        proposal = TradeProposal(
            run_id=run_id,
            symbol=state["request"].ticker,
            side=Side(market.direction),
            entry_price=float(market.features["close"]),
            stop_loss=market.stop_loss,
            take_profit=market.take_profit,
            timeframe=state["request"].timeframe,
            market_timestamp=datetime.fromisoformat(market.data_timestamp),
            rationale=market.supporting_evidence,
            client_order_id=f"qp-{run_id}",
        )
        reasons.append(f"Proposal created from Python market analysis: {market.direction} {proposal.symbol}")
        return {"proposal": proposal, "reasons": reasons}

    def strategy_audit(self, state: WorkflowState) -> dict[str, Any]:
        try:
            result = self.rules_auditor.execute(state["context"], self.rules_auditor.audit, state["proposal"], state["market"], state["primary_data"])
            if result.decision == "FAIL":
                return {"rules": result, "outcome": FinalOutcome.REJECTED, "reasons": result.violations}
            return {"rules": result}
        except Exception as exc:
            return {"fatal_error": f"Strategy Auditor failed: {exc}", "outcome": FinalOutcome.REJECTED, "reasons": [str(exc)]}

    def risk_review(self, state: WorkflowState) -> dict[str, Any]:
        try:
            portfolio = self.portfolio_monitor.execute(state["context"], self.portfolio_monitor.review)
            result = self.risk_manager.execute(state["context"], self.risk_manager.evaluate, state["proposal"], state["market"], portfolio)
            if result.decision == "REJECTED":
                return {"risk": result, "portfolio": portfolio, "outcome": FinalOutcome.REJECTED, "reasons": result.violated_restrictions}
            return {"risk": result, "portfolio": portfolio}
        except Exception as exc:
            return {"fatal_error": f"Risk stage failed: {exc}", "outcome": FinalOutcome.REJECTED, "reasons": [str(exc)]}

    def position_sizing(self, state: WorkflowState) -> dict[str, Any]:
        try:
            result = self.money_manager.execute(state["context"], self.money_manager.size, state["proposal"], state["portfolio"])
            if result.decision == "REJECTED":
                return {"money": result, "outcome": FinalOutcome.REJECTED, "reasons": [result.explanation]}
            proposal = state["proposal"].model_copy(update={"quantity": result.quantity})
            return {"money": result, "proposal": proposal}
        except Exception as exc:
            return {"fatal_error": f"Money Manager failed: {exc}", "outcome": FinalOutcome.REJECTED, "reasons": [str(exc)]}

    def supervisor_review(self, state: WorkflowState) -> dict[str, Any]:
        try:
            result = self.supervisor.execute(state["context"], self.supervisor.review, state["proposal"], state["market"], state["news"], state["rules"], state["risk"], state["money"])
            if result.decision == "REJECTED":
                return {"supervisor": result, "outcome": FinalOutcome.REJECTED, "reasons": result.concerns}
            return {"supervisor": result}
        except Exception as exc:
            return {"fatal_error": f"Trade Supervisor failed: {exc}", "outcome": FinalOutcome.REJECTED, "reasons": [str(exc)]}

    def safety_validation(self, state: WorkflowState) -> dict[str, Any]:
        try:
            result = self.safety_engine.validate(state["proposal"], state.get("market"), state.get("rules"), state.get("risk"), state.get("money"), state.get("supervisor"))
            if not result.approved:
                return {"safety": result, "outcome": FinalOutcome.REJECTED, "reasons": result.violations}
            return {"safety": result}
        except Exception as exc:
            return {"fatal_error": f"Deterministic safety engine failed closed: {exc}", "outcome": FinalOutcome.REJECTED, "reasons": [str(exc)]}

    def paper_execution(self, state: WorkflowState) -> dict[str, Any]:
        if not state["request"].auto_execute:
            return {
                "outcome": FinalOutcome.APPROVED,
                "execution": ExecutionResult(executed=False, message="Trade approved; automatic paper execution disabled by request"),
            }
        try:
            result = self.order_manager.execute(state["proposal"])
            portfolio = self.portfolio_monitor.execute(state["context"], self.portfolio_monitor.review)
            return {"outcome": FinalOutcome.APPROVED, "execution": result, "portfolio": portfolio, "reasons": [result.message]}
        except Exception as exc:
            return {"outcome": FinalOutcome.REJECTED, "execution": ExecutionResult(executed=False, message=f"Paper execution failed closed: {exc}"), "reasons": [str(exc)]}

    def final_report(self, state: WorkflowState) -> dict[str, Any]:
        outcome = state.get("outcome", FinalOutcome.REJECTED)
        reasons = state.get("reasons", [])
        if state.get("fatal_error"):
            reasons = reasons + [state["fatal_error"]]
        if not reasons:
            reasons = [f"Workflow completed with {outcome.value}"]
        data_sources = {}
        if state.get("primary_data"):
            data_sources = {
                "primary": state["primary_data"].summary(),
                "higher_timeframe": state["higher_data"].summary() if state.get("higher_data") else None,
                "metric_provenance": "Python/pandas calculations",
                "llm_provenance": "Optional, separately labelled in supervisor output",
                "execution_provenance": "SIMULATED_PAPER_ONLY",
            }
        report = FinalReport(
            run_id=state["run_id"], outcome=outcome, reasons=reasons, proposal=state.get("proposal"),
            market=state.get("market"), news=state.get("news"), rules=state.get("rules"), risk=state.get("risk"),
            money=state.get("money"), supervisor=state.get("supervisor"), safety=state.get("safety"),
            execution=state.get("execution"), traces=state["context"].traces, data_sources=data_sources,
        )
        self.repository.save_run(state["request"], report)
        return {"report": report}

    def _initial_state(self, request: ResearchRequest) -> WorkflowState:
        return {"run_id": str(uuid.uuid4()), "request": request, "context": ExecutionContext()}

    def run(self, request: ResearchRequest) -> FinalReport:
        result = self.graph.invoke(self._initial_state(request))
        return result["report"]

    def stream(self, request: ResearchRequest):
        """Yield LangGraph node updates for live UI progress; final update contains the report."""
        yield from self.graph.stream(self._initial_state(request), stream_mode="updates")
