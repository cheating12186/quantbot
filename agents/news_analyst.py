"""News retrieval and transparent lexicon-based sentiment classification.

The analyst never invents headlines: every item in the output was returned by a
configured provider (deduplicated, with timestamps and URLs preserved). When no
provider can deliver data the analyst says so explicitly and continues without
pretending that current headlines were analyzed.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from agents.base import BaseAgent
from models.agent_outputs import AgentStatus, NewsAnalysisOutput, NewsItem, TraceSpan
from tools.news import NewsProvider, NewsUnavailable, sanitize_news_error


def _parse_iso(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed


def _diagnostics(provider: NewsProvider, availability: str, reason: str | None = None) -> dict[str, Any]:
    report = getattr(provider, "last_report", None) or {}
    attempts = report.get("attempts")
    if attempts is None:
        attempts = [{"provider": provider.name, "ok": bool(report.get("ok", False))}] if report else []
    diagnostics: dict[str, Any] = {
        "availability": availability,
        "provider": report.get("provider") or provider.name,
        "cache_hit": bool(report.get("cache_hit", False)),
        "retrieved_at": report.get("retrieved_at"),
        "attempts": attempts,
    }
    if reason:
        diagnostics["reason"] = sanitize_news_error(reason, 300)
    return diagnostics


class NewsSentimentAnalyst(BaseAgent):
    name = "News & Sentiment Analyst"
    POSITIVE = {"beat", "beats", "growth", "surge", "upgrade", "profit", "record", "approval", "expands", "bullish", "strong"}
    NEGATIVE = {"miss", "misses", "decline", "plunge", "downgrade", "loss", "lawsuit", "investigation", "recall", "bearish", "weak", "cuts"}
    EVENT_WORDS = {"earnings", "guidance", "acquisition", "merger", "dividend", "buyback", "fda", "fed", "inflation", "lawsuit"}

    def __init__(self, provider: NewsProvider):
        self.provider = provider

    def _sentiment(self, text: str) -> tuple[str, float]:
        words = set(text.lower().replace(",", " ").replace(".", " ").split())
        positive = len(words & self.POSITIVE)
        negative = len(words & self.NEGATIVE)
        score = (positive - negative) / max(positive + negative, 1)
        sentiment = "positive" if score > 0 else "negative" if score < 0 else "neutral" if words else "unknown"
        return sentiment, score

    def analyze(self, symbol: str, *, span: TraceSpan) -> NewsAnalysisOutput:
        try:
            with span.tool("retrieve_financial_news", symbol) as call:
                raw = self.provider.fetch(symbol)
                call.output_summary = f"Retrieved {len(raw)} timestamped news items"
        except NewsUnavailable as exc:
            span.status = AgentStatus.UNAVAILABLE
            diagnostics = _diagnostics(self.provider, "UNAVAILABLE", str(exc))
            return NewsAnalysisOutput(
                status=AgentStatus.UNAVAILABLE,
                availability="UNAVAILABLE",
                diagnostics=diagnostics,
                explanation=f"{sanitize_news_error(str(exc), 300)}; no news claims were generated",
                source=self.provider.name,
            )
        diagnostics = _diagnostics(self.provider, "AVAILABLE" if raw else "EMPTY")
        retrieved_at = _parse_iso(diagnostics.get("retrieved_at"))
        if not raw:
            return NewsAnalysisOutput(
                status=AgentStatus.SUCCESS,
                availability="EMPTY",
                diagnostics=diagnostics,
                retrieved_at=retrieved_at,
                explanation="Configured provider(s) responded successfully but returned no relevant news; sentiment remains unknown",
                source=self.provider.name,
            )
        items: list[NewsItem] = []
        events: set[str] = set()
        for entry in raw:
            text = f"{entry.get('title', '')} {entry.get('summary', '')}"
            sentiment, score = self._sentiment(text)
            items.append(NewsItem(
                title=entry.get("title", "Untitled"),
                source=entry.get("source", "unknown"),
                url=entry.get("url", ""),
                published_at=entry.get("published_at"),
                sentiment=sentiment,
                sentiment_score=score,
                summary=entry.get("summary", ""),
                symbols=list(entry.get("symbols", [])),
            ))
            lowered = text.lower()
            events.update(word for word in self.EVENT_WORDS if word in lowered)
        scores = [item.sentiment_score for item in items]
        average = sum(scores) / len(scores)
        sentiments = {item.sentiment for item in items}
        conflicting = "positive" in sentiments and "negative" in sentiments
        sentiment = "positive" if average > 0.1 else "negative" if average < -0.1 else "neutral"
        confidence = min(0.8, 0.2 + len(items) * 0.05) * (0.6 if conflicting else 1.0)
        cache_note = " (served from cache)" if diagnostics.get("cache_hit") else ""
        return NewsAnalysisOutput(
            status=AgentStatus.SUCCESS,
            availability="AVAILABLE",
            diagnostics=diagnostics,
            retrieved_at=retrieved_at,
            sentiment=sentiment,
            confidence=round(confidence, 4),
            items=items,
            conflicting_news=conflicting,
            events=sorted(events),
            explanation=f"Transparent keyword sentiment over {len(items)} retrieved item(s) from {diagnostics.get('provider')}{cache_note}; not an LLM-invented news summary.",
            source=self.provider.name,
        )
