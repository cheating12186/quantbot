"""QuantPilot premium Streamlit dashboard. Run: streamlit run app.py"""
from __future__ import annotations

import streamlit as st

from agents.orchestrator import QuantPilotOrchestrator

st.set_page_config(page_title="QuantPilot", page_icon="◈", layout="wide", initial_sidebar_state="expanded")

st.markdown("""
<style>
:root { --bg:#070b14; --panel:#0e1524; --line:#1e293b; --text:#e2e8f0; --muted:#94a3b8; }
.stApp { background: radial-gradient(circle at 80% -10%, #13223c 0, #070b14 38%, #05080f 100%); color:var(--text); }
[data-testid="stSidebar"] { background:#080d17; border-right:1px solid var(--line); }
[data-testid="stHeader"] { background:rgba(0,0,0,0); }
h1,h2,h3 { letter-spacing:-.025em; color:#f1f5f9; }
p,label,.stMarkdown { color:#aebbd0; }
[data-testid="stMetric"] { background:linear-gradient(145deg,rgba(17,26,43,.95),rgba(10,16,28,.95)); border:1px solid #1c2940; padding:16px 18px; border-radius:12px; box-shadow:0 8px 25px rgba(0,0,0,.14); }
[data-testid="stMetricLabel"] { color:#8291aa; font-size:.77rem; text-transform:uppercase; letter-spacing:.08em; }
[data-testid="stMetricValue"] { color:#f1f5f9; font-variant-numeric:tabular-nums; }
.stButton>button,.stDownloadButton>button { background:#17263f; color:#dbeafe; border:1px solid #2d496f; border-radius:8px; font-weight:600; }
.stButton>button:hover { border-color:#60a5fa; background:#1d3355; }
.stTextInput>div>div>input,.stTextArea textarea,.stNumberInput input { background:#0d1524; color:#e2e8f0; border:1px solid #26344b; }
.stTabs [data-baseweb="tab-list"] { border-bottom:1px solid #1e293b; }
.stTabs [data-baseweb="tab"] { color:#94a3b8; }
.stTabs [aria-selected="true"] { color:#60a5fa !important; }
.qp-brand { display:flex; align-items:center; gap:11px; padding:8px 0 20px; }
.qp-brand-mark { width:34px;height:34px;border:1px solid #3b82f6;border-radius:9px;display:grid;place-items:center;color:#60a5fa;font-size:21px;box-shadow:inset 0 0 18px #1d4ed844; }
.qp-brand-name { font-size:1.28rem;font-weight:750;color:#f8fafc;letter-spacing:-.04em; }
.qp-brand-sub { font-size:.66rem;color:#64748b;letter-spacing:.14em;text-transform:uppercase; }
.qp-section { margin:12px 0 20px; } .qp-section h2{margin:0;font-size:1.45rem}.qp-section p{margin:5px 0 0;color:#7f8da5;font-size:.9rem}
.qp-badge { display:inline-block;padding:5px 10px;border:1px solid;border-radius:6px;font-size:.74rem;font-weight:750;letter-spacing:.08em; }
.qp-provenance { display:flex;gap:12px;align-items:baseline;background:#0c1321;border-left:3px solid;padding:9px 12px;margin:6px 0;border-radius:0 6px 6px 0;font-size:.8rem; }
.qp-provenance b{color:#dbeafe}.qp-provenance span{color:#8291aa}
.qp-footer { border-top:1px solid #172033;margin-top:32px;padding-top:16px;color:#64748b;font-size:.76rem; }
[data-testid="stDataFrame"] { border:1px solid #1c2940;border-radius:8px; }
[data-testid="stAlert"] { background:#0d1727; border:1px solid #243652; color:#dbeafe; }
[data-testid="stAlert"] * { color:#cbd5e1; }
</style>
""", unsafe_allow_html=True)


@st.cache_resource
def get_app():
    return QuantPilotOrchestrator()


app = get_app()
with st.sidebar:
    st.markdown('<div class="qp-brand"><div class="qp-brand-mark">◈</div><div><div class="qp-brand-name">QuantPilot</div><div class="qp-brand-sub">Agentic market intelligence</div></div></div>', unsafe_allow_html=True)
    page = st.radio("Workspace", ["Overview", "Market Research", "AI Research Assistant", "Paper Trading", "Risk Management", "Backtesting", "Agent Monitoring"], label_visibility="collapsed")
    st.divider()
    st.markdown("**SYSTEM MODE**")
    st.success("PAPER TRADING ONLY", icon="🛡️")
    st.caption(f"Market provider: {app.settings.data_provider.upper()}")
    st.caption(f"Groq: {'CONNECTED · ' + app.settings.groq_model if app.llm.available else 'DETERMINISTIC MODE'}")
    st.caption("Synthetic fallback is always labelled. No real brokerage adapter exists.")

if page == "Overview":
    from dashboard import overview
    overview.render(app)
elif page == "Market Research":
    from dashboard import research
    research.render(app)
elif page == "AI Research Assistant":
    from dashboard import assistant
    assistant.render(app)
elif page == "Paper Trading":
    from dashboard import trading
    trading.render(app)
elif page == "Risk Management":
    from dashboard import risk
    risk.render(app)
elif page == "Backtesting":
    from dashboard import backtesting
    backtesting.render(app)
else:
    from dashboard import monitoring
    monitoring.render(app)

st.markdown('<div class="qp-footer">QuantPilot · Research and simulated execution only · Historical performance does not guarantee future returns · Not financial advice</div>', unsafe_allow_html=True)
