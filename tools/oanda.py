"""Read-only OANDA v20 practice-market candles and quotes.

This module intentionally contains no order endpoints. OANDA is a market-data
source only; QuantPilot executions remain in the independent paper broker.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx
import pandas as pd

from tools.market_data import MarketDataError, MarketDataProvider


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
        if timeframe not in self._granularities:
            raise MarketDataError(f"Unsupported OANDA timeframe: {timeframe}")
        instrument = self.instrument(symbol)
        payload = self._get(
            f"/v3/instruments/{instrument}/candles",
            {"granularity": self._granularities[timeframe], "count": min(max(rows + 1, 60), 5000), "price": "M"},
        )
        records = []
        for candle in payload.get("candles", []):
            # Completed bars avoid repainting indicator and crossover signals.
            if not candle.get("complete", False) or "mid" not in candle:
                continue
            mid = candle["mid"]
            records.append({
                "timestamp": candle["time"], "open": float(mid["o"]), "high": float(mid["h"]),
                "low": float(mid["l"]), "close": float(mid["c"]), "volume": float(candle.get("volume", 0)),
            })
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
