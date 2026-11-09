from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

COLORS = {"green": "#34d399", "red": "#fb7185", "blue": "#60a5fa", "amber": "#fbbf24", "muted": "#94a3b8"}


def status_badge(text: str):
    value = str(text).upper()
    color = COLORS["green"] if value in ("APPROVED", "PASS", "SUCCESS", "FILLED") else COLORS["amber"] if value in ("NO_TRADE", "UNAVAILABLE", "PENDING") else COLORS["red"]
    st.markdown(f'<span class="qp-badge" style="border-color:{color};color:{color}">{value}</span>', unsafe_allow_html=True)


def section(title: str, subtitle: str = ""):
    st.markdown(f'<div class="qp-section"><h2>{title}</h2><p>{subtitle}</p></div>', unsafe_allow_html=True)


def provenance(label: str, detail: str, kind: str = "python"):
    colors = {"actual": COLORS["blue"], "python": COLORS["green"], "llm": "#c084fc", "paper": COLORS["amber"]}
    st.markdown(f'<div class="qp-provenance" style="border-left-color:{colors[kind]}"><b>{label}</b><span>{detail}</span></div>', unsafe_allow_html=True)


def dark_layout(figure: go.Figure, height: int = 420):
    figure.update_layout(
        template="plotly_dark", height=height, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Inter, sans-serif", color="#cbd5e1"), margin=dict(l=20, r=20, t=50, b=20),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        xaxis=dict(gridcolor="#1e293b"), yaxis=dict(gridcolor="#1e293b"),
    )
    return figure


def model_dataframe(models: list, fields: list[str] | None = None) -> pd.DataFrame:
    if not models:
        return pd.DataFrame()
    rows = []
    for model in models:
        data = model.model_dump(mode="json") if hasattr(model, "model_dump") else model
        rows.append({key: data.get(key) for key in fields} if fields else data)
    return pd.DataFrame(rows)
