"""Public graph factory kept separate for LangGraph inspection and testing."""
from __future__ import annotations

from orchestration.workflow import TradingWorkflow


def build_trading_graph(workflow: TradingWorkflow):
    """Return the compiled stateful LangGraph used by the orchestrator."""
    return workflow.graph
