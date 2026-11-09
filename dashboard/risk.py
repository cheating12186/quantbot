from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from dashboard.common import dark_layout, provenance, section


def render(app):
    section("Risk management", "Independent capital controls, exposure, loss limits, and trading-halt status")
    snapshot = app.repository.snapshot()
    if snapshot.trading_halted:
        st.error("HARD TRADING HALT · " + ", ".join(snapshot.halt_reasons))
    else:
        st.success("No hard risk breach · deterministic safety gate active")
    provenance("PYTHON RISK ENGINE", "Limits are loaded from config/risk_config.yaml and rechecked before every execution.", "python")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Max risk / trade", f"{app.risk_config.max_risk_per_trade_pct:.1%}", f"${snapshot.equity * app.risk_config.max_risk_per_trade_pct:,.2f} current equity")
    c2.metric("Daily loss", f"{max(0, -snapshot.daily_pnl / snapshot.day_start_equity):.2%}", f"Limit {app.risk_config.max_daily_loss_pct:.1%}", delta_color="inverse")
    c3.metric("Drawdown", f"{snapshot.drawdown_pct:.2%}", f"Limit {app.risk_config.max_account_drawdown_pct:.1%}", delta_color="inverse")
    c4.metric("Portfolio risk", f"{snapshot.portfolio_risk_pct:.2%}", f"Limit {app.risk_config.max_portfolio_risk_pct:.1%}")
    left, right = st.columns(2)
    with left:
        st.subheader("Limit utilization")
        rows = [
            {"Control": "Daily loss", "Used %": min(100, max(0, -snapshot.daily_pnl / snapshot.day_start_equity) / app.risk_config.max_daily_loss_pct * 100)},
            {"Control": "Drawdown", "Used %": min(100, snapshot.drawdown_pct / app.risk_config.max_account_drawdown_pct * 100)},
            {"Control": "Portfolio risk", "Used %": min(100, snapshot.portfolio_risk_pct / app.risk_config.max_portfolio_risk_pct * 100)},
            {"Control": "Gross exposure", "Used %": min(100, snapshot.gross_exposure_pct / app.risk_config.max_gross_exposure_pct * 100)},
        ]
        figure = go.Figure(go.Bar(x=[r["Used %"] for r in rows], y=[r["Control"] for r in rows], orientation="h", marker_color=["#fb7185" if r["Used %"] >= 100 else "#60a5fa" for r in rows]))
        figure.update_xaxes(title="Percent of configured limit")
        st.plotly_chart(dark_layout(figure, 300), width="stretch")
    with right:
        st.subheader("Configured simulation policy")
        st.json(app.risk_config.model_dump())
    st.subheader("Open-position risk")
    rows = []
    for p in snapshot.open_positions:
        rows.append({"symbol": p.symbol, "side": p.side.value, "quantity": p.quantity, "unit risk": abs(p.entry_price - p.stop_loss), "open risk $": abs(p.entry_price - p.stop_loss) * p.quantity, "unrealized $": p.unrealized_pnl()})
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True) if rows else st.info("No open-position risk.")
    st.caption("These are configurable simulation defaults, not universal trading recommendations. Halts are persistent; use the paper-account reset API only for a deliberate demo reset.")
