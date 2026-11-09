"""Trading and execution contracts shared by agents, API, and broker."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field, field_validator, model_validator

from models.market import SUPPORTED_TIMEFRAMES
from tools.risk_calculations import risk_reward


def new_id() -> str:
    return str(uuid.uuid4())


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Side(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"


class OrderStatus(str, Enum):
    PENDING = "PENDING"
    FILLED = "FILLED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


class FinalOutcome(str, Enum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    NO_TRADE = "NO_TRADE"


class ResearchRequest(BaseModel):
    ticker: str = Field(min_length=1, max_length=16)
    timeframe: str = "1d"
    request: str = "Analyze this ticker for a rule-compliant paper trade."
    auto_execute: bool = True
    rows: int = Field(default=300, ge=60, le=2000)

    @field_validator("ticker")
    @classmethod
    def clean_ticker(cls, value: str) -> str:
        value = value.strip().upper().replace("/", "_")
        if not value.replace(".", "").replace("-", "").replace("_", "").isalnum():
            raise ValueError("Ticker may contain letters, numbers, dots, hyphens, slashes, and underscores")
        return value

    @field_validator("timeframe")
    @classmethod
    def valid_timeframe(cls, value: str) -> str:
        if value not in SUPPORTED_TIMEFRAMES:
            raise ValueError(f"Timeframe must be one of {SUPPORTED_TIMEFRAMES}")
        return value


class TradeProposal(BaseModel):
    proposal_id: str = Field(default_factory=new_id)
    run_id: str
    symbol: str
    side: Side
    order_type: OrderType = OrderType.MARKET
    entry_price: float = Field(gt=0)
    stop_loss: float = Field(gt=0)
    take_profit: float = Field(gt=0)
    quantity: float = Field(default=0, ge=0)
    timeframe: str
    market_timestamp: datetime
    rationale: list[str] = Field(default_factory=list)
    client_order_id: str

    @model_validator(mode="after")
    def validate_geometry(self):
        if self.side == Side.LONG and not (self.stop_loss < self.entry_price < self.take_profit):
            raise ValueError("LONG requires stop_loss < entry_price < take_profit")
        if self.side == Side.SHORT and not (self.take_profit < self.entry_price < self.stop_loss):
            raise ValueError("SHORT requires take_profit < entry_price < stop_loss")
        return self

    @property
    def risk_per_unit(self) -> float:
        return abs(self.entry_price - self.stop_loss)

    @property
    def risk_reward(self) -> float:
        return risk_reward(self.entry_price, self.stop_loss, self.take_profit, self.side.value)


class Order(BaseModel):
    order_id: str = Field(default_factory=new_id)
    client_order_id: str
    run_id: str | None = None
    symbol: str
    side: Side
    order_type: OrderType
    quantity: float = Field(gt=0)
    limit_price: float | None = Field(default=None, gt=0)
    stop_loss: float = Field(gt=0)
    take_profit: float = Field(gt=0)
    status: OrderStatus = OrderStatus.PENDING
    filled_quantity: float = 0
    average_fill_price: float | None = None
    fees: float = 0
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    rejection_reason: str | None = None


class Fill(BaseModel):
    fill_id: str = Field(default_factory=new_id)
    order_id: str
    symbol: str
    side: Side
    quantity: float = Field(gt=0)
    price: float = Field(gt=0)
    fees: float = Field(ge=0)
    slippage: float = Field(ge=0)
    timestamp: datetime = Field(default_factory=utc_now)
    reason: str = "ENTRY"


class Position(BaseModel):
    position_id: str = Field(default_factory=new_id)
    symbol: str
    side: Side
    quantity: float = Field(gt=0)
    entry_price: float = Field(gt=0)
    stop_loss: float = Field(gt=0)
    take_profit: float = Field(gt=0)
    opened_at: datetime = Field(default_factory=utc_now)
    mark_price: float = Field(default=0, gt=0)
    realized_pnl: float = 0
    entry_fees: float = 0

    def unrealized_pnl(self) -> float:
        sign = 1 if self.side == Side.LONG else -1
        return (self.mark_price - self.entry_price) * self.quantity * sign


class ExecutionResult(BaseModel):
    executed: bool
    message: str
    order: Order | None = None
    fill: Fill | None = None
