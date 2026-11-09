"""News retrieval and transparent lexicon-based sentiment classification."""
from __future__ import annotations

from agents.base import BaseAgent
from models.agent_outputs import AgentStatus, NewsAnalysisOutput, NewsItem, TraceSpan
from tools.news import NewsProvider, NewsUnavailable


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
            return NewsAnalysisOutput(status=AgentStatus.UNAVAILABLE, explanation=str(exc) + "; no news claims were generated", source=self.provider.name)
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
            ))
            lowered = text.lower()
            events.update(word for word in self.EVENT_WORDS if word in lowered)
        if not items:
            return NewsAnalysisOutput(status=AgentStatus.SUCCESS, explanation="Provider returned no relevant news; sentiment remains unknown", source=self.provider.name)
        scores = [item.sentiment_score for item in items]
        average = sum(scores) / len(scores)
        sentiments = {item.sentiment for item in items}
        conflicting = "positive" in sentiments and "negative" in sentiments
        sentiment = "positive" if average > 0.1 else "negative" if average < -0.1 else "neutral"
        confidence = min(0.8, 0.2 + len(items) * 0.05) * (0.6 if conflicting else 1.0)
        return NewsAnalysisOutput(
            status=AgentStatus.SUCCESS,
            sentiment=sentiment,
            confidence=round(confidence, 4),
            items=items,
            conflicting_news=conflicting,
            events=sorted(events),
            explanation=f"Transparent keyword sentiment over {len(items)} retrieved item(s); not an LLM-invented news summary.",
            source=self.provider.name,
        )
