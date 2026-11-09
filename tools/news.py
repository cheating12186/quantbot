"""Pluggable financial-news providers with an explicit fallback chain.

Design rules:
- Absence of a provider is explicit, never fabricated. Only articles actually
  returned by a provider are ever exposed.
- Providers can be swapped without touching the News Analyst or the workflow;
  selecting ``auto`` builds a chain of the configured providers.
- Availability is reported as AVAILABLE (articles retrieved), EMPTY (providers
  responded successfully but returned nothing relevant) or UNAVAILABLE (no
  configured provider could deliver usable data).
- Results may be cached briefly to respect rate limits. Cached payloads keep
  their original publication timestamps and the retrieval timestamp of the
  underlying fetch; nothing is presented as fresher than it is.
"""
from __future__ import annotations

import copy
import re
import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any

import httpx


class NewsUnavailable(RuntimeError):
    """Provider (or chain) cannot deliver usable news right now.

    ``category`` is a short, sanitized machine-readable reason suitable for
    diagnostics output. It never contains credentials or provider payloads.
    """

    def __init__(self, message: str, category: str = "UNAVAILABLE"):
        super().__init__(message)
        self.category = category


# ---------------------------------------------------------------------------
# Item hygiene: normalization, validation, deduplication
# ---------------------------------------------------------------------------

_WS = re.compile(r"\s+")
_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)


def normalize_headline(headline: str) -> str:
    lowered = _PUNCT.sub(" ", (headline or "").lower())
    return _WS.sub(" ", lowered).strip()


def normalize_url(url: str) -> str:
    value = (url or "").strip().lower()
    value = re.sub(r"^https?://", "", value)
    value = value.split("#", 1)[0].rstrip("/")
    return value


def dedupe_articles(items: list[dict[str, Any]], limit: int | None = None) -> list[dict[str, Any]]:
    """Drop duplicate articles using a stable identifier (URL, else headline)."""
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for item in items:
        title = (item.get("title") or "").strip()
        if not title:
            continue
        key = normalize_url(item.get("url", "")) if item.get("url") else ""
        if not key:
            key = "headline:" + normalize_headline(title)
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
        if limit is not None and len(unique) >= limit:
            break
    return unique


def _parse_timestamp(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, str):
        text = value.strip()
        if text.isdigit():
            return _parse_timestamp(int(text))
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            match = re.match(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})\.\d{3,}(\+00:00|Z)?$", text)
            if not match:
                return None
            try:
                parsed = datetime.fromisoformat(match.group(1) + "+00:00")
            except ValueError:
                return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    return None


def _iso_utc(value: datetime | None) -> str | None:
    return value.isoformat().replace("+00:00", "Z") if value else None


def _sanitize(text: str, limit: int = 200) -> str:
    """Redact token-like material and trim provider diagnostics for display."""
    redacted = re.sub(r"(?i)(token|api[-_]?key|apikey|authorization|bearer)\s*[=:]\s*\S+", r"\1=[REDACTED]", str(text))
    redacted = re.sub(r"(?i)x-finnhub-token[\"']?\s*[:=]\s*[\"']?\S+", "x-finnhub-token=[REDACTED]", redacted)
    return _WS.sub(" ", redacted).strip()[:limit]


sanitize_news_error = _sanitize


class TTLNewsCache:
    """Small in-memory TTL cache. Cached entries retain original timestamps."""

    def __init__(self, ttl_seconds: int = 300, clock=time.time, max_entries: int = 256):
        self.ttl_seconds = max(0, int(ttl_seconds))
        self.clock = clock
        self.max_entries = max_entries
        self._store: dict[str, tuple[float, datetime, list[dict[str, Any]]]] = {}

    def get(self, key: str):
        entry = self._store.get(key)
        if entry is None:
            return None
        inserted_at, retrieved_at, items = entry
        if self.ttl_seconds == 0 or self.clock() - inserted_at > self.ttl_seconds:
            self._store.pop(key, None)
            return None
        return copy.deepcopy(items), retrieved_at

    def set(self, key: str, items: list[dict[str, Any]], retrieved_at: datetime) -> None:
        if len(self._store) >= self.max_entries:
            oldest = sorted(self._store.items(), key=lambda pair: pair[1][0])[: self.max_entries // 2]
            for stale_key, _ in oldest:
                self._store.pop(stale_key, None)
        self._store[key] = (self.clock(), retrieved_at, copy.deepcopy(items))


class NewsProvider(ABC):
    name = "abstract"
    requires_key = False

    def __init__(self, cache: TTLNewsCache | None = None, sleeper=time.sleep):
        self._cache = cache
        self._sleep = sleeper
        self.last_report: dict[str, Any] | None = None

    def fetch(self, symbol: str, limit: int = 10) -> list[dict[str, Any]]:
        symbol = (symbol or "").strip().upper()
        limit = max(1, int(limit))
        cache_key = f"{self.name}:{_cache_symbol(symbol)}:{limit}"
        if self._cache is not None:
            cached = self._cache.get(cache_key)
            if cached is not None:
                items, retrieved_at = cached
                retrieved_at = retrieved_at or datetime.now(timezone.utc)
                self.last_report = {
                    "provider": self.name,
                    "ok": True,
                    "availability": "AVAILABLE" if items else "EMPTY",
                    "cache_hit": True,
                    "items": len(items),
                    "retrieved_at": _iso_utc(retrieved_at),
                }
                return items
        items = self._fetch(symbol, limit)
        cleaned = dedupe_articles(items, limit)
        retrieved_at = datetime.now(timezone.utc)
        if self._cache is not None:
            self._cache.set(cache_key, cleaned, retrieved_at)
        self.last_report = {
            "provider": self.name,
            "ok": True,
            "availability": "AVAILABLE" if cleaned else "EMPTY",
            "cache_hit": False,
            "items": len(cleaned),
            "retrieved_at": _iso_utc(retrieved_at),
        }
        return cleaned

    @abstractmethod
    def _fetch(self, symbol: str, limit: int) -> list[dict[str, Any]]:
        raise NotImplementedError


def _cache_symbol(symbol: str) -> str:
    return symbol.replace("/", "_").replace("-", "_").upper()


def _item(title: str, source: str, url: str, published: Any, summary: str, symbols: list[str]) -> dict[str, Any] | None:
    title = (title or "").strip()
    if not title:
        return None
    published_at = _parse_timestamp(published)
    cleaned_symbols = []
    for raw in symbols or []:
        token = str(raw).strip().upper().replace("/", "_")
        if token and token not in cleaned_symbols:
            cleaned_symbols.append(token)
    return {
        "title": title,
        "source": (source or "unknown").strip() or "unknown",
        "url": (url or "").strip(),
        "published_at": published_at,
        "summary": _WS.sub(" ", (summary or "").strip())[:500],
        "symbols": cleaned_symbols,
    }


class NullNewsProvider(NewsProvider):
    name = "none"

    def __init__(self, reason: str = "No news provider is configured"):
        super().__init__()
        self.reason = reason

    def fetch(self, symbol: str, limit: int = 10) -> list[dict[str, Any]]:
        self.last_report = {
            "provider": self.name,
            "ok": False,
            "availability": "UNAVAILABLE",
            "cache_hit": False,
            "items": 0,
            "retrieved_at": None,
            "attempts": [{"provider": self.name, "ok": False, "category": "NOT_CONFIGURED", "error": self.reason}],
        }
        raise NewsUnavailable(self.reason, "NOT_CONFIGURED")

    def _fetch(self, symbol: str, limit: int) -> list[dict[str, Any]]:  # pragma: no cover - fetch is overridden
        raise NewsUnavailable(self.reason, "NOT_CONFIGURED")


def _forex_compact(symbol: str) -> str | None:
    """Return 'EURUSD' for 6-letter pair symbols, else None."""
    value = (symbol or "").upper().replace("/", "_").replace("-", "_")
    compact = value.replace("_", "")
    parts = value.split("_")
    if ("_" in value and len(parts) == 2 and all(p.isalpha() for p in parts)) or (len(compact) == 6 and compact.isalpha()):
        return compact
    return None


class YFinanceNewsProvider(NewsProvider):
    name = "yfinance"

    def _fetch(self, symbol: str, limit: int) -> list[dict[str, Any]]:
        normalized = symbol.strip().upper().replace("/", "_")
        compact = normalized.replace("_", "")
        yahoo_symbol = f"{compact}=X" if "_" in normalized and len(compact) == 6 and compact.isalpha() else normalized
        try:
            import yfinance as yf
            raw = yf.Ticker(yahoo_symbol).news or []
        except Exception as exc:
            raise NewsUnavailable(f"Yahoo Finance news retrieval failed: {_sanitize(exc)}", "PROVIDER_ERROR") from exc
        items: list[dict[str, Any]] = []
        for entry in raw[:limit]:
            content = entry.get("content", entry)
            provider = content.get("provider", {}) or {}
            canonical = content.get("canonicalUrl", {}) or content.get("clickThroughUrl", {}) or {}
            url = canonical.get("url", "") if isinstance(canonical, dict) else str(canonical)
            item = _item(
                title=content.get("title", ""),
                source=provider.get("displayName") or content.get("publisher", "unknown"),
                url=url,
                published=content.get("pubDate") or content.get("providerPublishTime"),
                summary=content.get("summary", ""),
                symbols=[compact] if compact else [],
            )
            if item:
                items.append(item)
        return items


class FinnhubNewsProvider(NewsProvider):
    """Finnhub market/company news (free tier: 60 calls/minute).

    Forex pairs use the general ``forex`` category feed; US equities use the
    ``company-news`` endpoint for the requested symbol. The API key is sent
    in the ``X-Finnhub-Token`` header so it never appears in URLs or logs.
    """

    name = "finnhub"
    requires_key = True

    def __init__(self, api_key: str, cache: TTLNewsCache | None = None, sleeper=time.sleep, client: httpx.Client | None = None):
        super().__init__(cache=cache, sleeper=sleeper)
        if not api_key:
            raise NewsUnavailable("FINNHUB_API_KEY (or legacy NEWS_API_KEY) is not configured", "NOT_CONFIGURED")
        self._client = client or httpx.Client(
            base_url="https://finnhub.io/api/v1",
            headers={"X-Finnhub-Token": api_key},
            timeout=httpx.Timeout(15.0),
        )

    def _get_json(self, path: str, params: dict[str, Any]) -> Any:
        attempts = 3  # 1 initial try + 2 bounded retries
        last_exc: Exception | None = None
        for attempt in range(attempts):
            try:
                response = self._client.get(path, params=params)
            except Exception as exc:
                last_exc = exc
                if attempt < attempts - 1:
                    self._sleep(0.5 * (2 ** attempt))
                    continue
                raise NewsUnavailable(f"Finnhub request failed: {_sanitize(exc)}", "NETWORK_ERROR") from exc
            status = response.status_code
            if status == 200:
                try:
                    return response.json()
                except Exception as exc:
                    raise NewsUnavailable("Finnhub returned an unreadable response body", "BAD_RESPONSE") from exc
            if status in (401, 403):
                raise NewsUnavailable(f"Finnhub rejected the configured API key (HTTP {status})", "AUTH_ERROR")
            if status == 404:
                raise NewsUnavailable("Finnhub endpoint not found (HTTP 404)", "NOT_FOUND")
            if status == 429 or status >= 500:
                last_exc = NewsUnavailable(f"Finnhub returned HTTP {status}", "RATE_LIMITED" if status == 429 else "UPSTREAM_ERROR")
                if attempt < attempts - 1:
                    retry_after = response.headers.get("Retry-After")
                    try:
                        wait = float(retry_after) if retry_after else 0.5 * (2 ** attempt)
                    except ValueError:
                        wait = 0.5 * (2 ** attempt)
                    self._sleep(min(wait, 5.0))
                    continue
                raise last_exc
            raise NewsUnavailable(f"Finnhub returned HTTP {status}", f"HTTP_{status}")
        raise NewsUnavailable(f"Finnhub request failed: {_sanitize(last_exc) if last_exc else 'unknown error'}", "NETWORK_ERROR")

    def _fetch(self, symbol: str, limit: int) -> list[dict[str, Any]]:
        compact = _forex_compact(symbol)
        if compact:
            payload = self._get_json("/news", {"category": "forex"})
            related_hint = compact
        else:
            from datetime import timedelta
            today = datetime.now(timezone.utc).date()
            payload = self._get_json(
                "/company-news",
                {"symbol": symbol.upper(), "from": (today - timedelta(days=14)).isoformat(), "to": today.isoformat()},
            )
            related_hint = symbol.upper()
        if not isinstance(payload, list):
            raise NewsUnavailable("Finnhub returned an unexpected payload shape", "BAD_RESPONSE")
        items: list[dict[str, Any]] = []
        for entry in payload:
            if not isinstance(entry, dict):
                continue
            related = str(entry.get("related") or "").strip()
            symbols = [s for s in re.split(r"[,;\s]+", related) if s] if related else [related_hint]
            item = _item(
                title=entry.get("headline") or entry.get("title") or "",
                source=entry.get("source") or "unknown",
                url=entry.get("url") or "",
                published=entry.get("datetime"),
                summary=entry.get("summary") or "",
                symbols=symbols,
            )
            if item:
                items.append(item)
        return items[:limit]


class ChainedNewsProvider(NewsProvider):
    """Ordered fallback chain. First provider returning usable articles wins.

    Providers that fail are recorded in ``last_report['attempts']`` with a
    sanitized category; providers that respond with zero articles count as a
    successful-but-empty answer. If every provider fails the chain raises
    ``NewsUnavailable`` and news is explicitly UNAVAILABLE.
    """

    def __init__(self, providers: list[NewsProvider], cache: TTLNewsCache | None = None, name: str = "auto"):
        super().__init__(cache=cache)
        self.providers = list(providers)
        self.name = name

    def fetch(self, symbol: str, limit: int = 10) -> list[dict[str, Any]]:
        instrument = (symbol or "").strip().upper()
        limit = max(1, int(limit))
        cache_key = f"{self.name}:{_cache_symbol(instrument)}:{limit}"
        if self._cache is not None:
            cached = self._cache.get(cache_key)
            if cached is not None:
                items, retrieved_at = cached
                self.last_report = {
                    "availability": "AVAILABLE" if items else "EMPTY",
                    "provider": "cache",
                    "cache_hit": True,
                    "retrieved_at": _iso_utc(retrieved_at),
                    "items": len(items),
                    "attempts": [{"provider": "cache", "ok": True, "items": len(items), "cache_hit": True}],
                }
                return items

        attempts: list[dict[str, Any]] = []
        saw_success = False
        latest_retrieval: str | None = None
        for provider in self.providers:
            started = time.monotonic()
            try:
                items = provider.fetch(instrument, limit)
            except NewsUnavailable as exc:
                attempts.append({
                    "provider": provider.name,
                    "ok": False,
                    "category": getattr(exc, "category", "PROVIDER_ERROR"),
                    "error": _sanitize(str(exc)),
                    "duration_ms": round((time.monotonic() - started) * 1000, 2),
                })
                continue
            leaf = provider.last_report or {}
            retrieved_at = leaf.get("retrieved_at")
            latest_retrieval = latest_retrieval or retrieved_at
            try:
                parsed_retrieved = _parse_timestamp(retrieved_at) if retrieved_at else None
                duration_ms = round((time.monotonic() - started) * 1000, 2)
            except Exception:
                parsed_retrieved = None
                duration_ms = round((time.monotonic() - started) * 1000, 2)
            attempts.append({
                "provider": provider.name,
                "ok": True,
                "items": len(items),
                "cache_hit": bool(leaf.get("cache_hit")),
                "retrieved_at": retrieved_at,
                "duration_ms": duration_ms,
            })
            saw_success = True
            if items:
                self.last_report = {
                    "availability": "AVAILABLE",
                    "provider": provider.name,
                    "cache_hit": bool(leaf.get("cache_hit")),
                    "retrieved_at": retrieved_at,
                    "items": len(items),
                    "attempts": attempts,
                }
                if self._cache is not None:
                    self._cache.set(cache_key, items, parsed_retrieved or datetime.now(timezone.utc))
                return items
        availability = "EMPTY" if saw_success else "UNAVAILABLE"
        self.last_report = {
            "availability": availability,
            "provider": None,
            "cache_hit": False,
            "retrieved_at": latest_retrieval,
            "items": 0,
            "attempts": attempts,
        }
        if availability == "EMPTY":
            if self._cache is not None:
                self._cache.set(cache_key, [], datetime.now(timezone.utc))
            return []
        failed = ", ".join(f"{a['provider']}:{a.get('category', 'ERROR')}" for a in attempts) or "no providers configured"
        raise NewsUnavailable(f"No news provider could deliver usable data ({failed})", "UNAVAILABLE")

    def _fetch(self, symbol: str, limit: int) -> list[dict[str, Any]]:  # pragma: no cover - fetch is overridden
        return self.fetch(symbol, limit)


def _chain_names(provider_name: str, finnhub_configured: bool) -> list[str]:
    if provider_name == "auto":
        names = (["finnhub"] if finnhub_configured else []) + ["yfinance"]
        return names
    if provider_name == "none":
        return []
    return [provider_name]


def describe_news_chain(provider_name: str, finnhub_configured: bool = False) -> list[str]:
    """Human-readable provider order used for integration status output."""
    return _chain_names((provider_name or "none").lower(), finnhub_configured)


def build_news_provider(
    name: str,
    *,
    finnhub_api_key: str = "",
    news_api_key: str = "",
    cache_ttl_seconds: int = 300,
    sleeper=time.sleep,
) -> NewsProvider:
    """Build the configured provider (or fallback chain).

    ``NEWS_API_KEY`` is honoured as a legacy alias for ``FINNHUB_API_KEY``; if
    the key you hold belongs to another service, set ``FINNHUB_API_KEY``
    instead. ``auto`` chains Finnhub (when a key is configured) followed by
    the keyless yfinance fallback.
    """
    selected = (name or "none").strip().lower()
    cache = TTLNewsCache(cache_ttl_seconds) if cache_ttl_seconds and cache_ttl_seconds > 0 else None
    key = finnhub_api_key or news_api_key

    def finnhub() -> FinnhubNewsProvider:
        return FinnhubNewsProvider(key, cache=cache, sleeper=sleeper)

    def yfinance() -> YFinanceNewsProvider:
        return YFinanceNewsProvider(cache=cache, sleeper=sleeper)

    if selected == "auto":
        providers: list[NewsProvider] = []
        if key:
            providers.append(finnhub())
        providers.append(yfinance())
        return ChainedNewsProvider(providers, cache=cache, name="auto")
    if selected == "finnhub":
        if not key:
            return NullNewsProvider("NEWS_PROVIDER=finnhub but FINNHUB_API_KEY (or legacy NEWS_API_KEY) is not configured")
        return finnhub()
    if selected in ("yfinance", "yahoo"):
        return yfinance()
    return NullNewsProvider()
