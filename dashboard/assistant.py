from __future__ import annotations

import pandas as pd
import streamlit as st

from dashboard.common import model_dataframe, provenance, section, status_badge
from models.trade import ResearchRequest


def render(app):
    section("AI research assistant", "Submit an objective, inspect every agent, and approve only through deterministic controls")
    with st.form("agent_request"):
        c1, c2 = st.columns([2, 1])
        ticker = c1.text_input("Ticker", "AAPL").upper()
        timeframe = c2.selectbox("Trading timeframe", ["5m", "15m", "1h", "1d"], index=3)
        objective = st.text_area("Natural-language objective", "Analyze this ticker for a high-quality EMA crossover setup. Reject the trade if any strategy or risk rule fails.", height=100)
        auto_execute = st.checkbox("Execute automatically only if every check passes", value=False)
        submitted = st.form_submit_button("Launch specialized agents", type="primary", width="stretch")
    if submitted:
        request = ResearchRequest(ticker=ticker, timeframe=timeframe, request=objective, auto_execute=auto_execute)
        try:
            with st.status("Coordinating QuantPilot agents…", expanded=True) as status:
                labels = {
                    "validate_input": "Request validated · paper-only controls armed",
                    "fetch_market_data": "Multi-timeframe OHLCV retrieved and validated",
                    "parallel_analysis": "Market and news agents completed independent analysis",
                    "create_proposal": "Opportunity gate evaluated",
                    "strategy_audit": "Strategy rules audited in Python",
                    "risk_review": "Risk Manager completed independent veto review",
                    "position_sizing": "Money Manager calculated cost-aware quantity",
                    "supervisor_review": "Trade Supervisor completed consistency review",
                    "safety_validation": "Deterministic safety engine repeated mandatory checks",
                    "paper_execution": "Paper execution stage completed",
                }
                report = None
                for update in app.workflow.stream(request):
                    for node, node_state in update.items():
                        if node in labels:
                            st.write("✓ " + labels[node])
                        if node_state.get("report"):
                            report = node_state["report"]
                        elif node_state.get("fatal_error"):
                            st.write("⚠ " + node_state["fatal_error"])
                if report is None:
                    raise RuntimeError("Workflow ended without a final report")
                st.write(f"Workflow complete: {report.outcome.value}")
                status.update(label=f"Agent workflow · {report.outcome.value}", state="complete" if report.outcome.value != "REJECTED" else "error")
            st.session_state.latest_report = report
        except Exception as exc:
            st.error(f"Workflow failed closed: {exc}")
    report = st.session_state.get("latest_report")
    if not report:
        st.info("No research run in this session. Historical runs remain available in Agent Monitoring.")
        return
    c1, c2, c3 = st.columns([1, 2, 2])
    with c1:
        status_badge(report.outcome.value)
    c2.metric("Proposal quantity", f"{report.proposal.quantity:g}" if report.proposal else "—")
    c3.metric("Agent stages / tool calls", f"{len(report.traces)} / {sum(len(t.tool_calls) for t in report.traces)}")
    st.write("**Decision evidence**")
    for reason in report.reasons:
        st.markdown(f"• {reason}")
    provenance("PYTHON METRICS", "Indicators, confidence, risk, sizing, rules, and safety checks are deterministic.", "python")
    if report.supervisor and "GROQ" in report.supervisor.review_source:
        provenance("LLM INTERPRETATION", report.supervisor.review_source + " · advisory review only", "llm")
    else:
        provenance("LLM STATUS", "Groq not configured or not used; no LLM claims were substituted for analysis.", "llm")
    provenance("PAPER EXECUTION", report.execution.message if report.execution else "No execution attempted", "paper")
    tabs = st.tabs(["Agent timeline", "Market", "Rules", "Risk & sizing", "Supervisor & safety", "News", "Raw report"])
    with tabs[0]:
        rows = [{"agent": t.agent, "status": t.status.value, "duration_ms": t.duration_ms, "tools": len(t.tool_calls), "tokens": t.input_tokens + t.output_tokens, "error": t.error} for t in report.traces]
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
        for trace in report.traces:
            with st.expander(f"{trace.agent} · {trace.status.value} · {trace.duration_ms:.1f} ms"):
                for tool in trace.tool_calls:
                    st.code(f"{tool.tool} [{tool.status.value}] {tool.duration_ms:.2f}ms\nIN: {tool.input_summary}\nOUT: {tool.output_summary}\nERROR: {tool.error or 'none'}")
    with tabs[1]:
        st.json(report.market.model_dump(mode="json") if report.market else {"status": "NOT_RUN"})
    with tabs[2]:
        st.json(report.rules.model_dump(mode="json") if report.rules else {"status": "NOT_RUN"})
    with tabs[3]:
        c1, c2 = st.columns(2)
        c1.json(report.risk.model_dump(mode="json") if report.risk else {"status": "NOT_RUN"})
        c2.json(report.money.model_dump(mode="json") if report.money else {"status": "NOT_RUN"})
    with tabs[4]:
        c1, c2 = st.columns(2)
        c1.json(report.supervisor.model_dump(mode="json") if report.supervisor else {"status": "NOT_RUN"})
        c2.json(report.safety.model_dump(mode="json") if report.safety else {"status": "NOT_RUN"})
    with tabs[5]:
        st.json(report.news.model_dump(mode="json") if report.news else {"status": "NOT_RUN"})
    with tabs[6]:
        st.json(report.model_dump(mode="json"))
