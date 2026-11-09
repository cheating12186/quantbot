from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from agents.orchestrator import QuantPilotOrchestrator
from api.dependencies import get_quantpilot
from models.portfolio import PortfolioSnapshot
from models.trade import Fill, Order, Position

router = APIRouter(prefix="/api/v1/paper", tags=["Paper portfolio"])


class CandleRequest(BaseModel):
    symbol: str
    open: float = Field(gt=0)
    high: float = Field(gt=0)
    low: float = Field(gt=0)
    close: float = Field(gt=0)


class CloseRequest(BaseModel):
    quantity: float = Field(gt=0)
    market_price: float = Field(gt=0)


@router.get("/portfolio", response_model=PortfolioSnapshot)
def portfolio(app: QuantPilotOrchestrator = Depends(get_quantpilot)):
    return app.repository.snapshot()


@router.get("/risk/config")
def risk_config(app: QuantPilotOrchestrator = Depends(get_quantpilot)):
    return app.risk_config.model_dump()


@router.get("/positions", response_model=list[Position])
def positions(app: QuantPilotOrchestrator = Depends(get_quantpilot)):
    return app.repository.positions()


@router.get("/orders", response_model=list[Order])
def orders(app: QuantPilotOrchestrator = Depends(get_quantpilot)):
    return app.repository.orders()


@router.get("/fills", response_model=list[Fill])
def fills(app: QuantPilotOrchestrator = Depends(get_quantpilot)):
    return app.repository.fills()


@router.get("/equity")
def equity(app: QuantPilotOrchestrator = Depends(get_quantpilot)):
    return app.repository.equity_history()


@router.get("/journal")
def journal(app: QuantPilotOrchestrator = Depends(get_quantpilot)):
    return app.repository.journal()


@router.post("/candles", response_model=list[Fill])
def process_candle(candle: CandleRequest, app: QuantPilotOrchestrator = Depends(get_quantpilot)):
    """Replay a candle through pending limits and protective exits (paper only)."""
    return app.broker.process_candle(candle.symbol, candle.open, candle.high, candle.low, candle.close)


@router.delete("/orders/{order_id}", response_model=Order)
def cancel_order(order_id: str, app: QuantPilotOrchestrator = Depends(get_quantpilot)):
    return app.broker.cancel_order(order_id)


@router.post("/positions/{symbol}/close", response_model=Fill)
def close_position(symbol: str, request: CloseRequest, app: QuantPilotOrchestrator = Depends(get_quantpilot)):
    return app.broker.close_position(symbol.upper(), request.quantity, request.market_price)


@router.post("/reset", response_model=PortfolioSnapshot)
def reset_paper_account(app: QuantPilotOrchestrator = Depends(get_quantpilot)):
    app.repository.reset()
    return app.repository.snapshot()
