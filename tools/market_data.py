"""Historical OHLCV providers and strict data-quality checks.

No network access is required for tests. Synthetic data is deterministic and is
always labelled; it must never be mistaken for observed market data.
"""
from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Callable

import numpy as np
import pandas as pd

from models.market import (
    OHLCV_COLUMNS,
    SUPPORTED_TIMEFRAMES,
    DataIssue,
    DataQuality,
    MarketDataset,
)


class MarketDataError(RuntimeError):
    pass


class MarketDataValidationError(MarketDataError):
    def __init__(self, message: str, quality: DataQuality):
        super().__init__(message)
        self.quality = quality


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def normalize_ohlcv(frame: pd.DataFrame) -> pd.DataFrame:
    """Return sorted, unique, UTC-indexed, lower-case OHLCV data."""
    if frame is None or frame.empty:
        return pd.DataFrame(columns=list(OHLCV_COLUMNS), index=pd.DatetimeIndex([], tz="UTC"))
    result = frame.copy()
    if isinstance(result.columns, pd.MultiIndex):
        result.columns = result.columns.get_level_values(0)
    result.columns = [str(column).strip().lower().replace(" ", "_") for column in result.columns]
    if not isinstance(result.index, pd.DatetimeIndex):
        result.index = pd.to_datetime(result.index, errors="coerce", utc=True)
    elif result.index.tz is None:
        result.index = result.index.tz_localize("UTC")
    else:
        result.index = result.index.tz_convert("UTC")
    result = result[~result.index.isna()]
    result = result[~result.index.duplicated(keep="last")].sort_index()
    for column in OHLCV_COLUMNS:
        if column in result:
            result[column] = pd.to_numeric(result[column], errors="coerce")
    return result


def inspect_market_data(
    frame: pd.DataFrame,
    *,
    source: str = "unknown",
    timeframe: str = "1d",
    now: datetime | None = None,
    max_age_minutes: int | None = None,
    min_rows: int = 30,
    is_synthetic: bool = False,
) -> DataQuality:
    issues: list[DataIssue] = []
    if timeframe not in SUPPORTED_TIMEFRAMES:
        issues.append(DataIssue(code="TIMEFRAME", message=f"Unsupported timeframe: {timeframe}"))
    normalized = normalize_ohlcv(frame)
    if normalized.empty:
        issues.append(DataIssue(code="EMPTY", message="Market data response was empty"))
        return DataQuality(valid=False, source=source, issues=issues, is_synthetic=is_synthetic)
    missing_columns = [column for column in OHLCV_COLUMNS if column not in normalized.columns]
    if missing_columns:
        issues.append(DataIssue(code="COLUMNS", message=f"Missing columns: {', '.join(missing_columns)}"))
    if len(normalized) < min_rows:
        issues.append(DataIssue(code="INSUFFICIENT", message=f"Only {len(normalized)} rows; {min_rows} required"))
    if not normalized.index.is_monotonic_increasing:
        issues.append(DataIssue(code="ORDER", message="Timestamps are not chronological"))
    if normalized.index.has_duplicates:
        issues.append(DataIssue(code="DUPLICATES", message="Duplicate timestamps remain after normalization"))
    available = normalized[list(OHLCV_COLUMNS)] if not missing_columns else normalized
    if available.isna().any().any():
        count = int(available.isna().sum().sum())
        issues.append(DataIssue(code="MISSING", message=f"OHLCV contains {count} missing/non-numeric values"))
    if not missing_columns:
        invalid_ohlc = (
            (normalized["high"] < normalized[["open", "close", "low"]].max(axis=1))
            | (normalized["low"] > normalized[["open", "close", "high"]].min(axis=1))
            | (normalized[list(OHLCV_COLUMNS[:4])] <= 0).any(axis=1)
            | (normalized["volume"] < 0)
        )
        if invalid_ohlc.any():
            issues.append(DataIssue(code="OHLC", message=f"{int(invalid_ohlc.sum())} rows have invalid OHLCV relationships"))
    if max_age_minutes is not None:
        reference = now or utc_now()
        if reference.tzinfo is None:
            reference = reference.replace(tzinfo=timezone.utc)
        age_minutes = (reference - normalized.index[-1].to_pydatetime()).total_seconds() / 60
        if age_minutes > max_age_minutes:
            issues.append(DataIssue(
                code="STALE",
                message=f"Latest bar is {age_minutes:.0f} minutes old; limit is {max_age_minutes}",
            ))
    quality = DataQuality(
        valid=not any(issue.fatal for issue in issues),
        rows=len(normalized),
        start=normalized.index[0].to_pydatetime(),
        end=normalized.index[-1].to_pydatetime(),
        source=source,
        is_synthetic=is_synthetic,
        issues=issues,
    )
    return quality


def validate_market_data(frame: pd.DataFrame, **kwargs) -> pd.DataFrame:
    quality = inspect_market_data(frame, **kwargs)
    if not quality.valid:
        raise MarketDataValidationError("; ".join(issue.message for issue in quality.issues), quality)
    return normalize_ohlcv(frame)


class MarketDataProvider(ABC):
    name = "abstract"
    is_synthetic = False

    @abstractmethod
    def history(self, symbol: str, timeframe: str, rows: int = 300) -> pd.DataFrame:
        raise NotImplementedError

    def forming_candle(self, symbol: str, timeframe: str) -> dict[str, Any] | None:
        """Return the provider's current incomplete candle for live charts only.

        Confirmed decisions (indicators, research, backtesting, paper orders)
        must use ``history()`` — completed candles only. Subclasses that can
        report a forming candle override this; the default is ``None`` ("not
        available"), which never fabricates intrabar data.
        """
        return None


class YFinanceProvider(MarketDataProvider):
    name = "yfinance"
    _intervals = {"5m": "5m", "15m": "15m", "1h": "60m", "1d": "1d"}
    _periods = {"5m": "5d", "15m": "1mo", "1h": "6mo", "1d": "2y"}

    def history(self, symbol: str, timeframe: str, rows: int = 300) -> pd.DataFrame:
        if timeframe not in self._intervals:
            raise MarketDataError(f"Unsupported timeframe {timeframe}")
        try:
            import yfinance as yf
            yahoo_symbol = symbol
            compact = symbol.replace("_", "")
            if "_" in symbol and len(compact) == 6 and compact.isalpha():
                yahoo_symbol = f"{compact}=X"
            data = yf.download(
                yahoo_symbol,
                period=self._periods[timeframe],
                interval=self._intervals[timeframe],
                auto_adjust=False,
                actions=False,
                progress=False,
                threads=False,
                timeout=12,
            )
        except Exception as exc:
            raise MarketDataError(f"Yahoo Finance retrieval failed for {symbol}: {exc}") from exc
        if data is None or data.empty:
            raise MarketDataError(f"Yahoo Finance returned no data for {symbol} ({timeframe})")
        result = normalize_ohlcv(data).tail(rows)
        # Yahoo FX occasionally rounds the traded high/low independently from
        # open/close. Repair only discrepancies <= 10 bps and disclose the repair;
        # larger inconsistencies remain present and fail strict validation.
        high_reference = result[["open", "close"]].max(axis=1)
        low_reference = result[["open", "close"]].min(axis=1)
        high_gap = high_reference - result["high"]
        low_gap = result["low"] - low_reference
        repair_high = (high_gap > 0) & (high_gap / high_reference <= 0.001)
        repair_low = (low_gap > 0) & (low_gap / low_reference <= 0.001)
        result.loc[repair_high, "high"] = high_reference[repair_high]
        result.loc[repair_low, "low"] = low_reference[repair_low]
        repaired = int(repair_high.sum() + repair_low.sum())
        if repaired:
            result.attrs["repair_warning"] = f"Yahoo rounding normalization repaired {repaired} OHLC bound(s) at <=10 bps"
        return result


class SyntheticMarketDataProvider(MarketDataProvider):
    """Reproducible geometric OHLCV data for demos, labelled as synthetic."""
    name = "synthetic"
    is_synthetic = True
    _frequencies = {"5m": "5min", "15m": "15min", "1h": "1h", "1d": "1D"}

    def history(self, symbol: str, timeframe: str, rows: int = 300) -> pd.DataFrame:
        if timeframe not in self._frequencies:
            raise MarketDataError(f"Unsupported timeframe {timeframe}")
        seed = int(hashlib.sha256(f"{symbol}:{timeframe}".encode()).hexdigest()[:8], 16)
        rng = np.random.default_rng(seed)
        # End on a recent complete bar. It is intentionally synthetic, not a live quote.
        end = pd.Timestamp.now(tz="UTC").floor(self._frequencies[timeframe])
        index = pd.date_range(end=end, periods=rows, freq=self._frequencies[timeframe], tz="UTC")
        drift = 0.00025 if timeframe == "1d" else 0.00008
        returns = rng.normal(drift, 0.008 if timeframe == "1d" else 0.0025, rows)
        close = 100 * np.exp(np.cumsum(returns))
        open_ = np.r_[close[0] * (1 - returns[0]), close[:-1]]
        spread = np.maximum(close * rng.uniform(0.001, 0.006, rows), 0.01)
        high = np.maximum(open_, close) + spread
        low = np.minimum(open_, close) - spread
        volume = rng.integers(100_000, 2_000_000, rows).astype(float)
        return pd.DataFrame(
            {"open": open_, "high": high, "low": low, "close": close, "volume": volume}, index=index
        )


class MarketDataService:
    def __init__(
        self,
        provider: MarketDataProvider | None = None,
        *,
        fallback: MarketDataProvider | None = None,
        max_data_age: dict[str, int] | None = None,
        clock: Callable[[], datetime] = utc_now,
    ):
        self.provider = provider or YFinanceProvider()
        self.fallback = fallback
        self.max_data_age = max_data_age or {}
        self.clock = clock

    def fetch(self, symbol: str, timeframe: str, rows: int = 300) -> MarketDataset:
        symbol = symbol.strip().upper()
        symbol = symbol.replace("/", "_")
        if not symbol or not symbol.replace(".", "").replace("-", "").replace("_", "").isalnum():
            raise MarketDataError("Ticker must be a valid stock or instrument symbol")
        try:
            frame = self.provider.history(symbol, timeframe, rows)
            provider = self.provider
            warning = None
        except MarketDataError:
            if self.fallback is None:
                raise
            frame = self.fallback.history(symbol, timeframe, rows)
            provider = self.fallback
            warning = "Primary provider failed; deterministic synthetic fallback used. Not actual market data."
        provider_metadata = dict(getattr(frame, "attrs", {}) or {})
        normalized = normalize_ohlcv(frame)
        quality = inspect_market_data(
            normalized,
            source=provider.name,
            timeframe=timeframe,
            now=self.clock(),
            max_age_minutes=self.max_data_age.get(timeframe),
            min_rows=min(60, rows),
            is_synthetic=provider.is_synthetic,
        )
        # Provider fallback errors are fatal. Staleness is retained in metadata and
        # independently enforced by the safety engine at execution time.
        non_stale_fatal = [i for i in quality.issues if i.fatal and i.code != "STALE"]
        if non_stale_fatal:
            raise MarketDataValidationError("; ".join(i.message for i in non_stale_fatal), quality)
        if warning:
            quality.issues.append(DataIssue(code="SYNTHETIC_FALLBACK", message=warning, fatal=False))
        if provider_metadata.get("repair_warning"):
            quality.issues.append(DataIssue(code="PROVIDER_ROUNDING_REPAIR", message=provider_metadata["repair_warning"], fatal=False))
        return MarketDataset(
            symbol=symbol,
            timeframe=timeframe,
            frame=normalized,
            source=provider.name,
            quality=quality,
            retrieved_at=self.clock(),
            is_synthetic=provider.is_synthetic,
            metadata=provider_metadata,
        )

    def forming_candle(self, symbol: str, timeframe: str) -> dict[str, Any]:
        """Chart-only forming (incomplete) candle for the *primary* provider.

        Never raises and never substitutes synthetic data: providers without a
        forming-candle concept return ``forming: None`` with an explicit
        ``reason``. The result carries ``complete: False`` so callers cannot
        mistake it for confirmed OHLCV.
        """
        symbol = symbol.strip().upper().replace("/", "_")
        if timeframe not in SUPPORTED_TIMEFRAMES:
            return {"symbol": symbol, "timeframe": timeframe, "forming": None,
                    "completed_tail": None, "error": f"Unsupported timeframe: {timeframe}",
                    "retrieved_at": self.clock().isoformat()}
        provider_forming = getattr(self.provider, "forming_candle", None)
        if not callable(provider_forming):
            return {"symbol": symbol, "timeframe": timeframe, "forming": None,
                    "completed_tail": None, "reason": "Provider does not report a forming candle",
                    "retrieved_at": self.clock().isoformat()}
        try:
            payload = provider_forming(symbol, timeframe)
        except MarketDataError as exc:
            return {"symbol": symbol, "timeframe": timeframe, "forming": None,
                    "completed_tail": None, "error": str(exc)[:200],
                    "retrieved_at": self.clock().isoformat()}
        except Exception as exc:  # defensive: chart path must degrade, not crash
            return {"symbol": symbol, "timeframe": timeframe, "forming": None,
                    "completed_tail": None, "error": f"Forming candle unavailable: {type(exc).__name__}",
                    "retrieved_at": self.clock().isoformat()}
        if payload is None:
            return {"symbol": symbol, "timeframe": timeframe, "forming": None,
                    "completed_tail": None, "reason": "Provider does not report a forming candle",
                    "retrieved_at": self.clock().isoformat()}
        return payload
