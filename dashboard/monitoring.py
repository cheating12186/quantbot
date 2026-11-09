from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from dashboard.common import dark_layout, provenance, section


def render(app):
    section("Agent monitoring", "Execution traces, latency, tools, token usage, errors, decisions, and disagreements")
    provenance("EXECUTION EVIDENCE", "Traces are recorded during actual agent execution and persisted with each research run.", "python")
    runs = app.repository.runs(100)
    selected = st.selectbox("Research run", ["ALL"] + [f"{r['run_id']} · {r['ticker']} · {r['outcome']}" for r in runs])
    run_id = None if selected == "ALL" else selected.split(" · ")[0]
    traces = app.repository.traces(run_id)
    if not traces:
        st.info("No agent traces recorded yet.")
        return
    frame = pd.DataFrame([{"agent": t["agent"], "status": t["status"], "duration_ms": t["duration_ms"], "tools": len(t.get("tool_calls", [])), "input_tokens": t.get("input_tokens", 0), "output_tokens": t.get("output_tokens", 0), "error": t.get("error")} for t in traces])
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Agent executions", len(frame))
    c2.metric("Failed executions", int((frame.status == "FAILED").sum()))
    c3.metric("Tool calls", int(frame.tools.sum()))
    c4.metric("Total LLM tokens", int((frame.input_tokens + frame.output_tokens).sum()))
    st.dataframe(frame, width="stretch", hide_index=True)
    left, right = st.columns(2)
    with left:
        durations = frame.groupby("agent").duration_ms.mean().sort_values()
        figure = go.Figure(go.Bar(x=durations.values, y=durations.index, orientation="h", marker_color="#60a5fa"))
        st.plotly_chart(dark_layout(figure, 320), width="stretch")
    with right:
        st.subheader("Errors & unavailable capabilities")
        errors = frame[(frame.status == "FAILED") | (frame.status == "UNAVAILABLE")]
        st.dataframe(errors[["agent", "status", "error"]], width="stretch", hide_index=True) if not errors.empty else st.success("No failed or unavailable agent stages in this selection.")
    if run_id:
        report = app.repository.get_run(run_id)
        if report:
            st.subheader("Decision & disagreements")
            st.write(f"**{report['outcome']}**")
            for reason in report.get("reasons", []):
                st.markdown(f"• {reason}")
            supervisor = report.get("supervisor") or {}
            st.json({"disagreements": supervisor.get("disagreements", []), "concerns": supervisor.get("concerns", []), "missing_information": supervisor.get("missing_information", [])})
            with st.expander("Complete execution report"):
                st.json(report)
    st.subheader("Decision history")
    st.dataframe(pd.DataFrame(runs), width="stretch", hide_index=True)
