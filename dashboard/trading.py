from __future__ import annotations

import pandas as pd
import streamlit as st

from dashboard.common import model_dataframe, provenance, section


def render(app):
    section("Paper trading", "Proposals, open orders, positions, protective exits, and immutable execution history")
    provenance("SIMULATED EXECUTIONS", "All fills include modelled fees and slippage. No real brokerage connection exists.", "paper")
    portfolio = app.repository.snapshot()
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Cash", f"${portfolio.cash:,.2f}")
    c2.metric("Realized P&L", f"${portfolio.realized_pnl:,.2f}")
    c3.metric("Unrealized P&L", f"${portfolio.unrealized_pnl:,.2f}")
    c4.metric("Open orders", sum(order.status.value == "PENDING" for order in app.repository.orders()))
    tabs = st.tabs(["Positions", "Open orders", "Execution history", "Research proposals", "Candle replay"])
    with tabs[0]:
        positions = app.repository.positions()
        st.dataframe(model_dataframe(positions), width="stretch", hide_index=True) if positions else st.info("No open positions.")
        if positions:
            with st.form("close_position"):
                c1, c2, c3 = st.columns(3)
                symbol = c1.selectbox("Position", [p.symbol for p in positions])
                selected = next(p for p in positions if p.symbol == symbol)
                quantity = c2.number_input("Quantity", min_value=0.000001, max_value=float(selected.quantity), value=float(selected.quantity), step=1.0)
                price = c3.number_input("Reference market price", min_value=0.01, value=float(selected.mark_price), step=0.1)
                if st.form_submit_button("Close / partially close"):
                    fill = app.broker.close_position(symbol, quantity, price)
                    st.success(f"Paper close filled at {fill.price:.4f}; fees ${fill.fees:.2f}")
                    st.rerun()
    with tabs[1]:
        orders = [o for o in app.repository.orders() if o.status.value == "PENDING"]
        st.dataframe(model_dataframe(orders), width="stretch", hide_index=True) if orders else st.info("No pending orders.")
        if orders:
            selected = st.selectbox("Pending order to cancel", [o.order_id for o in orders])
            if st.button("Cancel selected order"):
                app.broker.cancel_order(selected)
                st.success("Order cancelled")
                st.rerun()
    with tabs[2]:
        fills = app.repository.fills()
        st.dataframe(model_dataframe(fills), width="stretch", hide_index=True) if fills else st.info("No execution history.")
        st.subheader("All orders")
        st.dataframe(model_dataframe(app.repository.orders()), width="stretch", hide_index=True)
    with tabs[3]:
        runs = app.repository.runs(50)
        rows = []
        for run in runs:
            raw = app.repository.get_run(run["run_id"])
            proposal = raw.get("proposal") if raw else None
            if proposal:
                rows.append({"run_id": run["run_id"], "created_at": run["created_at"], "outcome": run["outcome"], **{k: proposal.get(k) for k in ("symbol", "side", "entry_price", "stop_loss", "take_profit", "quantity")}})
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True) if rows else st.info("No trade proposals yet.")
    with tabs[4]:
        st.caption("Replay an OHLC candle through pending limits and existing stops/targets. If both protective levels occur in one bar, stop-loss executes first.")
        with st.form("candle_replay"):
            c1, c2, c3, c4, c5 = st.columns(5)
            symbol = c1.text_input("Symbol", "AAPL").upper()
            open_ = c2.number_input("Open", value=100.0, min_value=0.01)
            high = c3.number_input("High", value=102.0, min_value=0.01)
            low = c4.number_input("Low", value=98.0, min_value=0.01)
            close = c5.number_input("Close", value=101.0, min_value=0.01)
            if st.form_submit_button("Process paper candle"):
                try:
                    fills = app.broker.process_candle(symbol, open_, high, low, close)
                    st.success(f"Processed; {len(fills)} fill(s)")
                    st.json([f.model_dump(mode="json") for f in fills])
                except Exception as exc:
                    st.error(str(exc))
