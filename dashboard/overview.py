from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from dashboard.common import dark_layout, model_dataframe, provenance, section


def render(app):
    section("Command center", "Live paper account, risk posture, execution history, and agent activity")
    portfolio = app.repository.snapshot()
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Account equity", f"${portfolio.equity/1000:,.1f}k", f"{(portfolio.equity/portfolio.initial_equity-1):+.2%}")
    c2.metric("Buying power", f"${portfolio.buying_power/1000:,.1f}k")
    c3.metric("Daily P&L", f"${portfolio.daily_pnl:,.2f}")
    c4.metric("Open positions", len(portfolio.open_positions))
    c5.metric("Drawdown", f"{portfolio.drawdown_pct:.2%}", delta=f"HWM ${portfolio.high_water_mark:,.0f}", delta_color="off")
    provenance("SIMULATED PAPER ACCOUNT", "Balances and fills are persisted in SQLite; no real money is involved.", "paper")
    left, right = st.columns([1.5, 1])
    with left:
        st.subheader("Equity trajectory")
        history = app.repository.equity_history()
        if history:
            frame = pd.DataFrame(history)
            frame["timestamp"] = pd.to_datetime(frame.timestamp)
            figure = go.Figure(go.Scatter(x=frame.timestamp, y=frame.equity, mode="lines", line=dict(color="#60a5fa", width=2), name="Paper equity"))
            lower, upper = float(frame.equity.min()), float(frame.equity.max())
            padding = max((upper - lower) * 0.1, portfolio.initial_equity * 0.001)
            figure.update_yaxes(range=[lower - padding, upper + padding], tickformat="$,.0f")
            st.plotly_chart(dark_layout(figure, 300), width="stretch")
        else:
            st.info("Equity history will appear after account activity.")
    with right:
        st.subheader("Exposure & protection")
        st.progress(min(portfolio.gross_exposure_pct / app.risk_config.max_gross_exposure_pct, 1.0), text=f"Gross exposure {portfolio.gross_exposure_pct:.1%}")
        st.progress(min(portfolio.portfolio_risk_pct / app.risk_config.max_portfolio_risk_pct, 1.0), text=f"Open risk {portfolio.portfolio_risk_pct:.1%}")
        if portfolio.trading_halted:
            st.error("TRADING HALTED · " + ", ".join(portfolio.halt_reasons))
        else:
            st.success("Risk controls armed · new entries permitted")
    positions, runs = st.columns(2)
    with positions:
        st.subheader("Open positions")
        data = model_dataframe(portfolio.open_positions, ["symbol", "side", "quantity", "entry_price", "mark_price", "stop_loss", "take_profit"])
        st.dataframe(data, width="stretch", hide_index=True) if not data.empty else st.caption("No open paper positions.")
    with runs:
        st.subheader("Recent agent decisions")
        history = app.repository.runs(8)
        if history:
            st.dataframe(pd.DataFrame(history)[["created_at", "ticker", "timeframe", "outcome"]], width="stretch", hide_index=True)
        else:
            st.caption("No agent decisions yet.")
    st.subheader("Recent simulated executions")
    fills = model_dataframe(app.repository.fills(8), ["timestamp", "symbol", "side", "quantity", "price", "fees", "reason"])
    st.dataframe(fills, width="stretch", hide_index=True) if not fills.empty else st.caption("No fills yet. Submit a request in AI Research Assistant.")
