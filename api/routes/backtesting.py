from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from agents.orchestrator import QuantPilotOrchestrator
from api.dependencies import get_quantpilot
from models.market import SUPPORTED_TIMEFRAMES
from tools.backtesting import BacktestConfig, BacktestResult, run_ema_crossover_backtest
from tools.market_data import MarketDataError

router = APIRouter(prefix="/api/v1/backtests", tags=["Backtesting"])


class BacktestRequest(BaseModel):
    ticker: str = "AAPL"
    timeframe: str = "1d"
    rows: int = Field(default=300, ge=60, le=2000)
    config: BacktestConfig = Field(default_factory=BacktestConfig)


@router.post("", response_model=BacktestResult)
def backtest(request: BacktestRequest, app: QuantPilotOrchestrator = Depends(get_quantpilot)):
    if request.timeframe not in SUPPORTED_TIMEFRAMES:
        raise HTTPException(status_code=422, detail="Unsupported timeframe")
    try:
        dataset = app.market_data.fetch(request.ticker, request.timeframe, request.rows)
        return run_ema_crossover_backtest(dataset.frame, request.config)
    except (MarketDataError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
