from __future__ import annotations

import math

from fastapi import APIRouter, Depends, HTTPException, Query

from agents.orchestrator import QuantPilotOrchestrator
from api.dependencies import get_quantpilot
from models.market import SUPPORTED_TIMEFRAMES
from tools.indicators import add_indicators
from tools.market_data import MarketDataError
from tools.oanda import OandaMarketDataProvider

router = APIRouter(prefix="/api/v1/market", tags=["Market data integrations"])

DOCUMENTED_GROQ_MODELS = [
    "llama-3.1-8b-instant",
    "llama-3.3-70b-versatile",
    "openai/gpt-oss-20b",
    "openai/gpt-oss-120b",
]


def oanda(app: QuantPilotOrchestrator) -> OandaMarketDataProvider:
    if not app.settings.oanda_api_key or not app.settings.oanda_account_id:
        raise HTTPException(status_code=503, detail="OANDA practice integration is not configured")
    return OandaMarketDataProvider(app.settings.oanda_api_key, app.settings.oanda_account_id)


@router.get("/candles/{symbol}")
def candles(
    symbol: str,
    timeframe: str = Query(default="1d"),
    rows: int = Query(default=300, ge=60, le=1000),
    app: QuantPilotOrchestrator = Depends(get_quantpilot),
):
    if timeframe not in SUPPORTED_TIMEFRAMES:
        raise HTTPException(status_code=422, detail="Unsupported timeframe")
    try:
        dataset = app.market_data.fetch(symbol, timeframe, rows)
        frame = add_indicators(dataset.frame)
        columns = ["open", "high", "low", "close", "volume", "ema_9", "ema_15", "ema_20", "ema_50", "ema_200", "rsi_14", "macd", "macd_signal", "macd_hist", "atr_14", "bb_upper", "bb_middle", "bb_lower", "vwap", "relative_volume"]
        records = []
        for timestamp, row in frame[columns].iterrows():
            records.append({
                "timestamp": timestamp.isoformat(),
                **{column: (float(row[column]) if math.isfinite(float(row[column])) else None) for column in columns},
            })
        return {"dataset": dataset.summary(), "candles": records}
    except MarketDataError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/quote/{symbol}")
def quote(symbol: str, app: QuantPilotOrchestrator = Depends(get_quantpilot)):
    try:
        return oanda(app).latest_price(symbol)
    except MarketDataError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/oanda/account")
def oanda_account(app: QuantPilotOrchestrator = Depends(get_quantpilot)):
    try:
        return oanda(app).account_summary()
    except MarketDataError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/integrations")
def integrations(app: QuantPilotOrchestrator = Depends(get_quantpilot)):
    live_models = app.llm.list_models() if app.llm.available else None
    return {
        "paper_only": True,
        "oanda": {
            "configured": bool(app.settings.oanda_api_key and app.settings.oanda_account_id),
            "environment": "practice",
            "mode": "MARKET_DATA_ONLY",
            "provider_selected": app.settings.data_provider,
        },
        "groq": {
            "configured": app.llm.available,
            "selected_model": app.settings.groq_model,
            "available_models": live_models.value if live_models and live_models.value else DOCUMENTED_GROQ_MODELS,
            "model_list_source": "LIVE_ACCOUNT_API" if live_models and live_models.value else "DOCUMENTED_PRODUCTION_MODELS",
            "error": live_models.error if live_models else ("GROQ_API_KEY not configured" if not app.llm.available else None),
        },
        "database": "PERSISTENT" if app.settings.database_url.startswith("postgresql") else "EPHEMERAL_SQLITE",
    }
