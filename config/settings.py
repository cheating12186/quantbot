"""Environment and YAML configuration with safe paper-trading defaults."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field

PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")


class RiskConfig(BaseModel):
    max_risk_per_trade_pct: float = Field(gt=0, le=0.05)
    max_daily_loss_pct: float = Field(gt=0, le=0.2)
    max_account_drawdown_pct: float = Field(gt=0, le=0.5)
    max_concurrent_positions: int = Field(ge=1)
    min_risk_reward: float = Field(gt=0)
    max_portfolio_risk_pct: float = Field(gt=0)
    max_position_notional_pct: float = Field(gt=0)
    max_gross_exposure_pct: float = Field(gt=0)
    max_atr_pct: float = Field(default=0.12, gt=0)
    fee_bps: float = Field(default=1.0, ge=0)
    slippage_bps: float = Field(default=2.0, ge=0)
    lot_size: float = Field(default=1.0, gt=0)
    default_equity: float = Field(default=100_000.0, gt=0)
    max_data_age_minutes: dict[str, int] = Field(default_factory=dict)


class StrategyConfig(BaseModel):
    name: str
    fast_ema: int = 9
    slow_ema: int = 15
    rsi_long_min: float = 55.0
    rsi_short_max: float = 45.0
    min_relative_volume: float = 0.8
    min_market_confidence: float = 0.60
    atr_stop_multiple: float = 1.5
    atr_target_multiple: float = 3.0
    higher_timeframe: dict[str, str] = Field(default_factory=dict)
    allowed_sessions_utc: list[dict[str, str]] = Field(default_factory=list)
    allow_long: bool = True
    allow_short: bool = True
    require_fresh_crossover: bool = True


class Settings(BaseModel):
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"
    database_url: str = f"sqlite:///{PROJECT_ROOT / 'quantpilot.db'}"
    data_provider: str = "auto"
    allow_synthetic_fallback: bool = True
    news_provider: str = "none"
    news_api_key: str = ""
    oanda_api_key: str = ""
    oanda_account_id: str = ""
    oanda_environment: str = "practice"
    paper_only: bool = True
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    llm_timeout_seconds: float = 20.0
    llm_max_retries: int = 2


def _yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings(
        groq_api_key=os.getenv("GROQ_API_KEY", ""),
        groq_model=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
        database_url=os.getenv("DATABASE_URL", "sqlite:////tmp/quantpilot.db" if os.getenv("VERCEL") else f"sqlite:///{PROJECT_ROOT / 'quantpilot.db'}"),
        data_provider=os.getenv("DATA_PROVIDER", "auto").lower(),
        allow_synthetic_fallback=os.getenv("ALLOW_SYNTHETIC_FALLBACK", "true").lower() == "true",
        news_provider=os.getenv("NEWS_PROVIDER", "none").lower(),
        news_api_key=os.getenv("NEWS_API_KEY", ""),
        oanda_api_key=os.getenv("OANDA_API_KEY", ""),
        oanda_account_id=os.getenv("OANDA_ACCOUNT_ID", ""),
        oanda_environment="practice",  # Real-money OANDA endpoints are intentionally unavailable.
        paper_only=True,  # Intentionally immutable: real-money execution is not implemented.
        api_host=os.getenv("API_HOST", "0.0.0.0"),
        api_port=int(os.getenv("API_PORT", "8000")),
        llm_timeout_seconds=float(os.getenv("LLM_TIMEOUT_SECONDS", "20")),
        llm_max_retries=int(os.getenv("LLM_MAX_RETRIES", "2")),
    )


@lru_cache(maxsize=1)
def get_risk_config() -> RiskConfig:
    return RiskConfig.model_validate(_yaml(PROJECT_ROOT / "config" / "risk_config.yaml"))


@lru_cache(maxsize=1)
def get_strategy_config() -> StrategyConfig:
    return StrategyConfig.model_validate(_yaml(PROJECT_ROOT / "config" / "strategy_config.yaml"))
