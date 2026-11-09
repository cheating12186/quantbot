"""Quantitative market analyst with an explainable scoring methodology."""
from __future__ import annotations

import math

import pandas as pd

from agents.base import BaseAgent
from config.settings import StrategyConfig
from models.agent_outputs import EntryZone, MarketAnalysisOutput, TraceSpan
from models.market import MarketDataset
from tools.indicators import add_indicators, support_resistance


def _number(value) -> float | None:
    try:
        number = float(value)
        return round(number, 8) if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


class MarketAnalyst(BaseAgent):
    name = "Market Analyst"

    def __init__(self, strategy: StrategyConfig):
        self.strategy = strategy

    def _frame(self, dataset: MarketDataset, span: TraceSpan) -> pd.DataFrame:
        with span.tool("add_indicators", f"{dataset.symbol} {dataset.timeframe}, {len(dataset.frame)} bars") as call:
            frame = add_indicators(dataset.frame)
            call.output_summary = f"Calculated {len(frame.columns) - 5} indicator columns"
            return frame

    def analyze(self, dataset: MarketDataset, higher: MarketDataset | None = None, *, span: TraceSpan) -> MarketAnalysisOutput:
        frame = self._frame(dataset, span)
        latest = frame.iloc[-1]
        close = float(latest["close"])
        atr = _number(latest["atr_14"])
        atr_value = atr if atr and atr > 0 else close * 0.01
        support, resistance = support_resistance(dataset.frame)
        with span.tool("score_market_regime", "Weighted price/trend/momentum/volume evidence") as call:
            score = 0
            supporting: list[str] = []
            conflicting: list[str] = []
            components: dict[str, float] = {}

            def vote(condition: bool, bullish: str, bearish: str, weight: int = 1, neutral: bool = False):
                nonlocal score
                if neutral:
                    return
                if condition:
                    score += weight
                    supporting.append(bullish)
                else:
                    score -= weight
                    conflicting.append(bearish)

            ema9, ema15 = _number(latest.ema_9), _number(latest.ema_15)
            ema50, ema200 = _number(latest.ema_50), _number(latest.ema_200)
            rsi_value = _number(latest.rsi_14)
            macd_hist = _number(latest.macd_hist)
            relative_volume = _number(latest.relative_volume)
            vwap_value = _number(latest.vwap)
            if ema9 is None or ema15 is None or rsi_value is None or atr is None:
                raise RuntimeError("Insufficient valid bars for EMA/RSI/ATR analysis")
            vote(ema9 > ema15, f"EMA 9 ({ema9:.2f}) is above EMA 15 ({ema15:.2f})", f"EMA 9 ({ema9:.2f}) is below EMA 15 ({ema15:.2f})", neutral=ema9 == ema15)
            components["ema_cross"] = 1.0 if ema9 > ema15 else -1.0 if ema9 < ema15 else 0.0
            if ema50 is not None:
                vote(close > ema50, f"Close {close:.2f} is above EMA 50 {ema50:.2f}", f"Close {close:.2f} is below EMA 50 {ema50:.2f}", neutral=close == ema50)
                components["ema_50"] = 1.0 if close > ema50 else -1.0 if close < ema50 else 0.0
            if ema50 is not None and ema200 is not None:
                vote(ema50 > ema200, f"EMA 50 {ema50:.2f} is above EMA 200 {ema200:.2f}", f"EMA 50 {ema50:.2f} is below EMA 200 {ema200:.2f}", neutral=ema50 == ema200)
                components["ema_200"] = 1.0 if ema50 > ema200 else -1.0 if ema50 < ema200 else 0.0
            if macd_hist is not None:
                vote(macd_hist > 0, f"MACD histogram is positive ({macd_hist:.4f})", f"MACD histogram is negative ({macd_hist:.4f})", neutral=abs(macd_hist) < 1e-12)
                components["macd"] = 1.0 if macd_hist > 1e-12 else -1.0 if macd_hist < -1e-12 else 0.0
            if rsi_value >= 55:
                vote(True, f"RSI {rsi_value:.1f} confirms bullish momentum", "")
                components["rsi"] = 1.0
            elif rsi_value <= 45:
                vote(False, "", f"RSI {rsi_value:.1f} confirms bearish momentum")
                components["rsi"] = -1.0
            else:
                components["rsi"] = 0.0
            if vwap_value is not None:
                vote(close > vwap_value, f"Price is above VWAP {vwap_value:.2f}", f"Price is below VWAP {vwap_value:.2f}", neutral=close == vwap_value)
                components["vwap"] = 1.0 if close > vwap_value else -1.0 if close < vwap_value else 0.0
            if close > resistance:
                score += 1
                supporting.append(f"Close broke above 20-bar resistance {resistance:.2f}")
                components["breakout"] = 1.0
            elif close < support:
                score -= 1
                conflicting.append(f"Close broke below 20-bar support {support:.2f}")
                components["breakout"] = -1.0
            else:
                components["breakout"] = 0.0
            if relative_volume is not None and relative_volume >= self.strategy.min_relative_volume:
                supporting.append(f"Relative volume {relative_volume:.2f} meets {self.strategy.min_relative_volume:.2f} threshold")
            elif relative_volume is not None:
                conflicting.append(f"Relative volume {relative_volume:.2f} is below {self.strategy.min_relative_volume:.2f} threshold")
            call.output_summary = f"Net evidence score {score}; {len(supporting)} supporting / {len(conflicting)} conflicting"

        higher_info: dict[str, object] = {}
        htf_adjustment = 0.0
        direction = "LONG" if score >= 3 else "SHORT" if score <= -3 else "NONE"
        if higher is not None:
            higher_frame = self._frame(higher, span)
            htf = higher_frame.iloc[-1]
            htf_direction = "NONE"
            if _number(htf.ema_20) is not None and _number(htf.ema_50) is not None:
                htf_direction = "LONG" if htf.ema_20 > htf.ema_50 else "SHORT" if htf.ema_20 < htf.ema_50 else "NONE"
            aligned = direction != "NONE" and htf_direction == direction
            if direction != "NONE" and htf_direction != direction:
                conflicting.append(f"Higher timeframe {higher.timeframe} trend is {htf_direction}, conflicting with {direction}")
                htf_adjustment = -0.08
            elif aligned:
                supporting.append(f"Higher timeframe {higher.timeframe} trend confirms {direction}")
                htf_adjustment = 0.05
            higher_info = {
                "timeframe": higher.timeframe,
                "direction": htf_direction,
                "aligned": aligned,
                "data_timestamp": higher.frame.index[-1].isoformat(),
                "ema_20": _number(htf.ema_20),
                "ema_50": _number(htf.ema_50),
            }
        else:
            higher_info = {"aligned": False, "direction": "UNKNOWN", "limitation": "Higher-timeframe data unavailable"}
            conflicting.append("Higher-timeframe confirmation is unavailable")
            htf_adjustment = -0.08

        max_score = max(len(components), 1)
        evidence_strength = min(abs(score) / max_score, 1.0)
        data_penalty = 0.05 if ema200 is None else 0.0
        confidence = max(0.0, min(0.95, 0.45 + 0.40 * evidence_strength + htf_adjustment - data_penalty))
        if direction == "NONE":
            confidence = min(confidence, 0.59)
        regime = "BULLISH" if direction == "LONG" else "BEARISH" if direction == "SHORT" else "SIDEWAYS"
        entry_zone = EntryZone(low=round(max(0.01, close - 0.20 * atr_value), 4), high=round(close + 0.20 * atr_value, 4))
        stop = target = None
        if direction == "LONG":
            stop = round(close - self.strategy.atr_stop_multiple * atr_value, 4)
            target = round(close + self.strategy.atr_target_multiple * atr_value, 4)
        elif direction == "SHORT":
            stop = round(close + self.strategy.atr_stop_multiple * atr_value, 4)
            target = round(close - self.strategy.atr_target_multiple * atr_value, 4)
        limitations = [issue.message for issue in dataset.quality.issues]
        if len(frame) < 200 or ema200 is None:
            limitations.append("EMA 200 unavailable or not fully warmed up; long-term trend evidence was omitted")
        if dataset.is_synthetic:
            limitations.append("SYNTHETIC data: calculations demonstrate the engine but do not describe actual markets")
        features = {
            key: _number(latest[key]) for key in
            ("open", "high", "low", "close", "volume", "ema_9", "ema_15", "ema_20", "ema_50", "ema_200",
             "sma_20", "sma_50", "sma_200", "rsi_14", "macd", "macd_signal", "macd_hist", "atr_14", "bb_lower",
             "bb_middle", "bb_upper", "bb_width", "vwap", "relative_volume")
        }
        features.update({"support": round(support, 8), "resistance": round(resistance, 8), "evidence_score": float(score)})
        return MarketAnalysisOutput(
            market_regime=regime,
            direction=direction,
            confidence=round(confidence, 4),
            entry_zone=entry_zone,
            stop_loss=stop,
            take_profit=target,
            supporting_evidence=supporting,
            conflicting_evidence=conflicting,
            data_timestamp=dataset.frame.index[-1].isoformat(),
            features=features,
            confidence_components={**components, "htf_adjustment": htf_adjustment, "data_penalty": data_penalty},
            higher_timeframe=higher_info,
            data_limitations=limitations,
            explanation=(
                f"{regime} regime from a deterministic evidence score of {score}. Confidence = 0.45 base + "
                f"0.40 × normalized evidence strength ({evidence_strength:.2f}) + higher-timeframe adjustment "
                f"({htf_adjustment:.2f}) - data penalty ({data_penalty:.2f}); capped to [0, 0.95]."
            ),
        )
