from __future__ import annotations

import math

from fastapi import APIRouter, Depends, HTTPException, Query

from agents.orchestrator import QuantPilotOrchestrator
from api.dependencies import get_quantpilot
from models.market import SUPPORTED_TIMEFRAMES
from tools.indicators import add_indicators
from tools.market_data import MarketDataError
from tools.news import describe_news_chain
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
        forming_payload = app.market_data.forming_candle(symbol, timeframe)
        return {
            "dataset": dataset.summary(),
            "candles": records,
            # Chart-only, additive and backward compatible. Never part of the
            # completed-candle list used for indicators or decisions.
            "forming_candle": forming_payload.get("forming"),
            "completed_tail": forming_payload.get("completed_tail"),
            "forming_retrieved_at": forming_payload.get("retrieved_at"),
            "forming_error": forming_payload.get("error") or forming_payload.get("reason"),
        }
    except MarketDataError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/candles/{symbol}/forming")
def forming_candle(
    symbol: str,
    timeframe: str = Query(default="1h"),
    app: QuantPilotOrchestrator = Depends(get_quantpilot),
):
    """Live (incomplete) candle for chart display only.

    Confirmed decisions must keep using `/candles/{symbol}` (completed bars).
    `completed_tail` is the latest provider-confirmed completed candle, so a
    chart refreshes in place and promotes exactly one candle per boundary.
    """
    if timeframe not in SUPPORTED_TIMEFRAMES:
        raise HTTPException(status_code=422, detail="Unsupported timeframe")
    payload = app.market_data.forming_candle(symbol, timeframe)
    return payload


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
    settings = app.settings
    finnhub_configured = bool(settings.finnhub_api_key or settings.news_api_key)
    news_analyst = getattr(getattr(app, "workflow", None), "news_analyst", None)
    news_report = getattr(getattr(news_analyst, "provider", None), "last_report", None)
    news_health = None
    if isinstance(news_report, dict):
        availability = news_report.get("availability") or ("AVAILABLE" if news_report.get("ok") else "UNAVAILABLE")
        news_health = {
            "availability": availability,
            "provider": news_report.get("provider"),
            "cache_hit": bool(news_report.get("cache_hit", False)),
            "retrieved_at": news_report.get("retrieved_at"),
            "attempts": news_report.get("attempts", []),
        }
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
        "news": {
            "provider_selected": settings.news_provider,
            "fallback_chain": describe_news_chain(settings.news_provider, finnhub_configured),
            "finnhub_configured": finnhub_configured,
            "cache_ttl_seconds": settings.news_cache_ttl_seconds,
            # Sanitized: provider names, availability, timestamps and safe
            # error categories only — never API keys or provider payloads.
            "last_health": news_health,
        },
        "database": "PERSISTENT" if app.settings.database_url.startswith("postgresql") else "EPHEMERAL_SQLITE",
    }
