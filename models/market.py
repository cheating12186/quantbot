"""Market-data contracts. OHLCV frames remain pandas objects at the boundary."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import pandas as pd
from pydantic import BaseModel, Field

SUPPORTED_TIMEFRAMES = ("5m", "15m", "1h", "1d")
OHLCV_COLUMNS = ("open", "high", "low", "close", "volume")


class DataIssue(BaseModel):
    code: str
    message: str
    fatal: bool = True


class DataQuality(BaseModel):
    valid: bool
    rows: int = 0
    start: datetime | None = None
    end: datetime | None = None
    source: str
    is_synthetic: bool = False
    issues: list[DataIssue] = Field(default_factory=list)

    @property
    def warnings(self) -> list[str]:
        return [issue.message for issue in self.issues if not issue.fatal]


@dataclass
class MarketDataset:
    symbol: str
    timeframe: str
    frame: pd.DataFrame
    source: str
    quality: DataQuality
    retrieved_at: datetime
    is_synthetic: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def summary(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "rows": len(self.frame),
            "source": self.source,
            "is_synthetic": self.is_synthetic,
            "data_timestamp": self.frame.index[-1].isoformat() if len(self.frame) else None,
            "retrieved_at": self.retrieved_at.isoformat(),
            "quality": self.quality.model_dump(mode="json"),
            "metadata": self.metadata,
        }
