from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from dashboard.common import dark_layout, provenance, section
from tools.backtesting import BacktestConfig, run_ema_crossover_backtest


def render(app):
    section("Backtesting laboratory", "Next-bar EMA crossover execution with costs, sizing, protective exits, and buy-and-hold context")
    provenance("HISTORICAL SIMULATION", "Signals form at close t and execute at open t+1. Results are not a guarantee of future returns.", "python")
    with st.form("backtest"):
        c1, c2, c3 = st.columns(3)
        ticker = c1.text_input("Ticker", "AAPL").upper()
        timeframe = c2.selectbox("Timeframe", ["5m", "15m", "1h", "1d"], index=3)
        rows = c3.number_input("Historical bars", 60, 1500, 300, step=20)
        c1, c2, c3, c4 = st.columns(4)
        fast = c1.number_input("Fast EMA", 2, 100, 9)
        slow = c2.number_input("Slow EMA", 3, 250, 15)
        risk = c3.number_input("Risk / trade %", 0.1, 5.0, 1.0, step=0.1) / 100
        allocation = c4.number_input("Max position %", 1.0, 100.0, 25.0, step=1.0) / 100
        c1, c2, c3, c4 = st.columns(4)
        stop = c1.number_input("ATR stop multiple", 0.1, 10.0, 1.5)
        target = c2.number_input("ATR target multiple", 0.1, 20.0, 3.0)
        fees = c3.number_input("Fees (bps)", 0.0, 100.0, 1.0)
        slippage = c4.number_input("Slippage (bps)", 0.0, 100.0, 2.0)
        allow_short = st.checkbox("Allow short signals", value=True)
        submitted = st.form_submit_button("Run historical backtest", type="primary", width="stretch")
    if submitted:
        try:
            with st.spinner("Running chronological event simulation…"):
                dataset = app.market_data.fetch(ticker, timeframe, int(rows))
                result = run_ema_crossover_backtest(dataset.frame, BacktestConfig(fast_ema=int(fast), slow_ema=int(slow), risk_per_trade_pct=risk, max_position_notional_pct=allocation, atr_stop_multiple=stop, atr_target_multiple=target, fee_bps=fees, slippage_bps=slippage, allow_short=allow_short))
            st.session_state.backtest_result = result
            st.session_state.backtest_source = dataset
        except Exception as exc:
            st.error(f"Backtest failed: {exc}")
    result = st.session_state.get("backtest_result")
    if not result:
        st.info("Configure and run a backtest to inspect the equity curve and trade-by-trade history.")
        return
    source = st.session_state.backtest_source
    st.caption(f"Data source: {source.source} · synthetic={source.is_synthetic} · {result.methodology}")
    m = result.metrics
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Total return", f"{m.total_return_pct:+.2f}%", f"Buy & hold {result.buy_and_hold_return_pct:+.2f}%")
    c2.metric("Max drawdown", f"{m.max_drawdown_pct:.2f}%")
    c3.metric("Sharpe / Sortino", f"{m.sharpe_ratio:.2f} / {m.sortino_ratio:.2f}")
    c4.metric("Win rate", f"{m.win_rate:.1%}", f"{m.trade_count} closed trades")
    c5.metric("Expectancy", f"${m.expectancy:,.2f}", f"PF {'∞' if m.profit_factor is None and m.trade_count else (f'{m.profit_factor:.2f}' if m.profit_factor is not None else '—')}")
    curve = pd.DataFrame([p.model_dump() for p in result.equity_curve])
    curve["timestamp"] = pd.to_datetime(curve.timestamp)
    figure = go.Figure()
    figure.add_trace(go.Scatter(x=curve.timestamp, y=curve.equity, name="Strategy equity", line=dict(color="#60a5fa", width=2)))
    figure.add_trace(go.Scatter(x=curve.timestamp, y=curve.buy_and_hold, name="Buy & hold", line=dict(color="#94a3b8", dash="dot")))
    st.plotly_chart(dark_layout(figure, 400), width="stretch")
    dd = go.Figure(go.Scatter(x=curve.timestamp, y=curve.drawdown * 100, fill="tozeroy", name="Drawdown %", line=dict(color="#fb7185")))
    st.plotly_chart(dark_layout(dd, 240), width="stretch")
    st.subheader("Trade-by-trade history")
    trades = pd.DataFrame([t.model_dump(mode="json") for t in result.trades])
    st.dataframe(trades, width="stretch", hide_index=True) if not trades.empty else st.info("No completed trades under these rules.")
    st.subheader("Performance diagnostics")
    st.json(m.model_dump())
