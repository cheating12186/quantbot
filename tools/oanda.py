"""Read-only OANDA v20 practice-market candles and quotes.

This module intentionally contains no order endpoints. OANDA is a market-data
source only; QuantPilot executions remain in the independent paper broker.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

import httpx
import pandas as pd

from tools.market_data import MarketDataError, MarketDataProvider


def _parse_rfc3339(value: Any) -> str | None:
    """Normalize an OANDA RFC3339 timestamp to canonical UTC (seconds precision)."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    match = re.match(r"^(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2})(\.\d+)?([+-]\d{2}:\d{2})?$", text)
    if not match:
        return None
    base, _fraction, offset = match.groups()
    try:
        parsed = datetime.strptime(base.replace(" ", "T") + (offset or "+00:00"), "%Y-%m-%dT%H:%M:%S%z")
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class OandaMarketDataProvider(MarketDataProvider):
    name = "oanda-practice"
    is_synthetic = False
    _granularities = {"5m": "M5", "15m": "M15", "1h": "H1", "1d": "D"}

    def __init__(
        self,
        api_key: str,
        account_id: str,
        environment: str = "practice",
        client: httpx.Client | None = None,
    ):
        if not api_key or not account_id:
            raise MarketDataError("OANDA_API_KEY and OANDA_ACCOUNT_ID are required for OANDA data")
        if environment != "practice":
            raise MarketDataError("QuantPilot permits only the OANDA practice environment")
        self.account_id = account_id
        self.base_url = "https://api-fxpractice.oanda.com"
        self._client = client or httpx.Client(
            base_url=self.base_url,
            headers={"Authorization": f"Bearer {api_key}", "Accept-Datetime-Format": "RFC3339"},
            timeout=httpx.Timeout(15.0),
        )

    @staticmethod
    def instrument(symbol: str) -> str:
        value = symbol.strip().upper().replace("/", "_").replace("-", "_")
        if "_" not in value and value.isalpha() and len(value) == 6:
            value = f"{value[:3]}_{value[3:]}"
        parts = value.split("_")
        if len(parts) != 2 or not all(part and part.isalnum() for part in parts):
            raise MarketDataError(f"Invalid OANDA instrument: {symbol}")
        return value

    def _candles_payload(self, instrument: str, timeframe: str, count: int) -> dict[str, Any]:
        return self._get(
            f"/v3/instruments/{instrument}/candles",
            {"granularity": self._granularities[timeframe], "count": min(max(int(count), 1), 5000), "price": "M"},
        )

    @staticmethod
    def _candle_item(candle: dict[str, Any]) -> dict[str, Any] | None:
        """Normalize one OANDA candle, preserving the ``complete`` flag.

        Returns ``None`` when the candle is missing or malformed — never
        invents prices. Timestamps are normalized to canonical UTC RFC3339.
        """
        mid = candle.get("mid") or {}
        try:
            open_, high, low, close = (float(mid[key]) for key in ("o", "h", "l", "c"))
        except (KeyError, TypeError, ValueError):
            return None
        timestamp = _parse_rfc3339(candle.get("time"))
        if timestamp is None:
            return None
        try:
            volume = float(candle.get("volume", 0) or 0)
        except (TypeError, ValueError):
            volume = 0.0
        return {
            "timestamp": timestamp,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
            "complete": bool(candle.get("complete", False)),
        }

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            response = self._client.get(path, params=params)
            response.raise_for_status()
            payload = response.json()
            if "errorMessage" in payload:
                raise MarketDataError(f"OANDA practice API error: {payload['errorMessage']}")
            return payload
        except MarketDataError:
            raise
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text[:300]
            raise MarketDataError(f"OANDA practice API returned HTTP {exc.response.status_code}: {detail}") from exc
        except Exception as exc:
            raise MarketDataError(f"OANDA practice data retrieval failed: {exc}") from exc

    def history(self, symbol: str, timeframe: str, rows: int = 300) -> pd.DataFrame:
        """Completed candles only — safe for indicators, research, backtests, orders."""
        if timeframe not in self._granularities:
            raise MarketDataError(f"Unsupported OANDA timeframe: {timeframe}")
        instrument = self.instrument(symbol)
        payload = self._candles_payload(instrument, timeframe, min(max(rows + 1, 60), 5000))
        records = []
        for candle in payload.get("candles", []):
            # Completed bars avoid repainting indicator and crossover signals.
            item = self._candle_item(candle)
            if item is None or not item["complete"]:
                continue
            records.append({key: item[key] for key in ("timestamp", "open", "high", "low", "close", "volume")})
        if not records:
            raise MarketDataError(f"OANDA returned no completed candles for {instrument} ({timeframe})")
        frame = pd.DataFrame(records).tail(rows)
        frame["timestamp"] = pd.to_datetime(frame.timestamp, utc=True)
        frame = frame.set_index("timestamp")
        try:
            frame.attrs["quote"] = self.latest_price(instrument)
        except MarketDataError as exc:
            frame.attrs["quote_error"] = str(exc)
        frame.attrs["instrument"] = instrument
        frame.attrs["environment"] = "practice"
        return frame

    def forming_candle(self, symbol: str, timeframe: str) -> dict[str, Any]:
        """The provider's current *incomplete* candle, for live chart display only.

        Uses the actual OANDA incomplete candle (same candles endpoint), never
        an approximation from sampled quotes. The returned candle is flagged
        ``complete: False`` and the payload also carries ``completed_tail`` —
        the latest provider-confirmed completed candle — so chart clients can
        promote exactly one candle at a timeframe boundary.
        """
        if timeframe not in self._granularities:
            raise MarketDataError(f"Unsupported OANDA timeframe: {timeframe}")
        instrument = self.instrument(symbol)
        payload = self._candles_payload(instrument, timeframe, 2)
        forming: dict[str, Any] | None = None
        completed_tail: dict[str, Any] | None = None
        for candle in payload.get("candles", []):
            item = self._candle_item(candle)
            if item is None:
                continue
            if item["complete"]:
                completed_tail = item
            else:
                forming = item
        return {
            "symbol": instrument,
            "timeframe": timeframe,
            "forming": forming,
            "completed_tail": completed_tail,
            "retrieved_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "environment": "practice",
            "source": self.name,
            "is_synthetic": False,
        }

    def latest_price(self, symbol: str) -> dict[str, Any]:
        instrument = self.instrument(symbol)
        payload = self._get(f"/v3/accounts/{self.account_id}/pricing", {"instruments": instrument})
        prices = payload.get("prices", [])
        if not prices:
            raise MarketDataError(f"OANDA returned no current price for {instrument}")
        price = prices[0]
        bid = float(price["bids"][0]["price"])
        ask = float(price["asks"][0]["price"])
        return {
            "instrument": instrument,
            "bid": bid,
            "ask": ask,
            "mid": (bid + ask) / 2,
            "spread": ask - bid,
            "timestamp": price.get("time"),
            "environment": "practice",
            "source": self.name,
            "is_synthetic": False,
        }

    def account_summary(self) -> dict[str, Any]:
        payload = self._get(f"/v3/accounts/{self.account_id}/summary")
        account = payload.get("account", {})
        # Return non-sensitive integration metadata, never balances used for trading.
        return {
            "id": account.get("id", self.account_id),
            "currency": account.get("currency"),
            "environment": "practice",
            "data_only": True,
        }
