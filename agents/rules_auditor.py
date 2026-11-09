"""Hard, deterministic EMA-crossover/RSI/HTF strategy validation."""
from __future__ import annotations

from datetime import time

from agents.base import BaseAgent
from config.settings import StrategyConfig
from models.agent_outputs import MarketAnalysisOutput, RuleEvidence, RulesAuditOutput, TraceSpan
from models.market import MarketDataset
from models.trade import Side, TradeProposal
from tools.indicators import add_indicators, crossed_above, crossed_below


class StrategyRulesAuditor(BaseAgent):
    name = "Strategy & Rules Auditor"

    def __init__(self, config: StrategyConfig):
        self.config = config

    def audit(self, proposal: TradeProposal, market: MarketAnalysisOutput, dataset: MarketDataset, *, span: TraceSpan) -> RulesAuditOutput:
        with span.tool("calculate_strategy_indicators", f"{dataset.symbol} {dataset.timeframe}") as call:
            frame = add_indicators(dataset.frame)
            call.output_summary = "EMA crossover, RSI, relative volume and session evidence calculated"
        latest = frame.iloc[-1]
        evidence: list[RuleEvidence] = []
        long = proposal.side == Side.LONG
        side_allowed = self.config.allow_long if long else self.config.allow_short
        evidence.append(RuleEvidence(rule="Side enabled", passed=side_allowed, observed=proposal.side.value, expected=self.config.allow_long if long else self.config.allow_short))
        cross = crossed_above(frame.ema_9, frame.ema_15) if long else crossed_below(frame.ema_9, frame.ema_15)
        trend_state = latest.ema_9 > latest.ema_15 if long else latest.ema_9 < latest.ema_15
        cross_pass = cross if self.config.require_fresh_crossover else trend_state
        evidence.append(RuleEvidence(
            rule="Fresh EMA 9/15 crossover" if self.config.require_fresh_crossover else "EMA 9/15 trend state",
            passed=bool(cross_pass),
            observed={"crossover": cross, "ema_9_previous": float(frame.ema_9.iloc[-2]), "ema_15_previous": float(frame.ema_15.iloc[-2]), "ema_9": float(latest.ema_9), "ema_15": float(latest.ema_15)},
            expected="EMA 9 crossed above EMA 15" if long else "EMA 9 crossed below EMA 15",
        ))
        rsi = float(latest.rsi_14)
        rsi_pass = rsi >= self.config.rsi_long_min if long else rsi <= self.config.rsi_short_max
        evidence.append(RuleEvidence(rule="RSI momentum confirmation", passed=bool(rsi_pass), observed=round(rsi, 4), expected=f">= {self.config.rsi_long_min}" if long else f"<= {self.config.rsi_short_max}"))
        htf_direction = str(market.higher_timeframe.get("direction", "UNKNOWN"))
        htf_pass = htf_direction == proposal.side.value
        evidence.append(RuleEvidence(rule="Higher-timeframe alignment", passed=htf_pass, observed=htf_direction, expected=proposal.side.value))
        relative_volume = float(latest.relative_volume)
        volume_pass = relative_volume >= self.config.min_relative_volume
        evidence.append(RuleEvidence(rule="Relative volume threshold", passed=bool(volume_pass), observed=round(relative_volume, 4), expected=f">= {self.config.min_relative_volume}"))
        geometry_pass = ((proposal.stop_loss < proposal.entry_price < proposal.take_profit) if long else (proposal.take_profit < proposal.entry_price < proposal.stop_loss))
        evidence.append(RuleEvidence(rule="Stop/target geometry", passed=geometry_pass, observed={"entry": proposal.entry_price, "stop": proposal.stop_loss, "target": proposal.take_profit}, expected="Directionally consistent positive prices"))
        timestamp = dataset.frame.index[-1]
        minute = timestamp.hour * 60 + timestamp.minute
        sessions = self.config.allowed_sessions_utc
        session_pass = False
        for session in sessions:
            start = time.fromisoformat(session["start"])
            end = time.fromisoformat(session["end"])
            start_minute, end_minute = start.hour * 60 + start.minute, end.hour * 60 + end.minute
            if start_minute <= end_minute:
                session_pass |= start_minute <= minute <= end_minute
            else:
                session_pass |= minute >= start_minute or minute <= end_minute
        if not sessions:
            session_pass = True
        evidence.append(RuleEvidence(rule="Permitted UTC trading session", passed=session_pass, observed=timestamp.isoformat(), expected=sessions or "ANY"))
        market_direction_pass = market.direction == proposal.side.value
        evidence.append(RuleEvidence(rule="Market direction consistency", passed=market_direction_pass, observed=market.direction, expected=proposal.side.value))
        violations = [f"{item.rule}: observed {item.observed}; expected {item.expected}" for item in evidence if not item.passed]
        decision = "PASS" if not violations else "FAIL"
        return RulesAuditOutput(
            decision=decision,
            rules_checked=[item.rule for item in evidence],
            violations=violations,
            evidence=evidence,
            explanation=f"Checked {len(evidence)} hard rules in Python; {len(violations)} violation(s) found.",
        )
