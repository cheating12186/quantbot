from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from dashboard.common import dark_layout, provenance, section, status_badge
from models.agent_outputs import ExecutionContext
from tools.indicators import add_indicators


def render(app):
    section("Market research", "OHLCV, Python-calculated indicators, multi-timeframe evidence, and optional news")
    with st.form("market_research"):
        c1, c2, c3 = st.columns([2, 1, 1])
        ticker = c1.text_input("Ticker", "AAPL").upper()
        timeframe = c2.selectbox("Timeframe", ["5m", "15m", "1h", "1d"], index=3)
        rows = c3.number_input("Bars", 60, 1000, 300, step=20)
        submitted = st.form_submit_button("Analyze market", width="stretch")
    if submitted or "research_dataset" not in st.session_state:
        try:
            with st.spinner("Retrieving and validating OHLCV data…"):
                dataset = app.market_data.fetch(ticker, timeframe, int(rows))
                htf_name = app.strategy_config.higher_timeframe.get(timeframe, timeframe)
                higher = dataset if htf_name == timeframe else app.market_data.fetch(ticker, htf_name, int(rows))
                context = ExecutionContext()
                analysis = app.workflow.market_analyst.execute(context, app.workflow.market_analyst.analyze, dataset, higher)
                news = app.workflow.news_analyst.execute(context, app.workflow.news_analyst.analyze, ticker)
            st.session_state.research_dataset = dataset
            st.session_state.research_analysis = analysis
            st.session_state.research_news = news
        except Exception as exc:
            st.error(f"Market research failed: {exc}")
            return
    dataset = st.session_state.research_dataset
    analysis = st.session_state.research_analysis
    news = st.session_state.research_news
    provenance(("SYNTHETIC DATA" if dataset.is_synthetic else "ACTUAL MARKET DATA"), f"Source: {dataset.source} · {len(dataset.frame)} bars · latest {dataset.frame.index[-1]}", "python" if dataset.is_synthetic else "actual")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Market regime", analysis.market_regime)
    c2.metric("Direction", analysis.direction)
    c3.metric("Explainable confidence", f"{analysis.confidence:.1%}")
    c4.metric("RSI · ATR", f"{analysis.features.get('rsi_14') or 0:.1f} · {analysis.features.get('atr_14') or 0:.2f}")
    status_badge(analysis.direction if analysis.direction != "NONE" else "NO_TRADE")
    frame = add_indicators(dataset.frame).tail(180)
    figure = make_subplots(rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.05, row_heights=[0.58, 0.20, 0.22], subplot_titles=("Price & trend", "RSI 14", "MACD"))
    figure.add_trace(go.Candlestick(x=frame.index, open=frame.open, high=frame.high, low=frame.low, close=frame.close, name="OHLC", increasing_line_color="#34d399", decreasing_line_color="#fb7185"), row=1, col=1)
    for period, color in [(9, "#60a5fa"), (15, "#c084fc"), (50, "#fbbf24"), (200, "#94a3b8")]:
        figure.add_trace(go.Scatter(x=frame.index, y=frame[f"ema_{period}"], name=f"EMA {period}", line=dict(color=color, width=1.3)), row=1, col=1)
    figure.add_trace(go.Scatter(x=frame.index, y=frame.rsi_14, name="RSI", line=dict(color="#60a5fa")), row=2, col=1)
    figure.add_hline(y=70, line_dash="dot", line_color="#fb7185", row=2, col=1)
    figure.add_hline(y=30, line_dash="dot", line_color="#34d399", row=2, col=1)
    figure.add_trace(go.Bar(x=frame.index, y=frame.macd_hist, name="MACD histogram", marker_color="#3b82f6"), row=3, col=1)
    figure.update_layout(height=720)
    st.plotly_chart(dark_layout(figure, 720), width="stretch")
    left, right = st.columns(2)
    with left:
        st.subheader("Supporting evidence")
        for item in analysis.supporting_evidence:
            st.markdown(f"✓ {item}")
        st.subheader("Higher timeframe")
        st.json(analysis.higher_timeframe)
    with right:
        st.subheader("Conflicts & limitations")
        for item in analysis.conflicting_evidence + analysis.data_limitations:
            st.markdown(f"• {item}")
        st.subheader("News & sentiment")
        st.write(f"**{news.sentiment.upper()}** · {news.explanation}")
        for item in news.items:
            st.markdown(f"[{item.title}]({item.url}) · {item.source} · {item.published_at} · {item.sentiment}")
    with st.expander("Confidence methodology & numerical features"):
        st.write(analysis.explanation)
        st.json(analysis.confidence_components)
        st.json(analysis.features)
