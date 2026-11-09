"use strict";
/*
 * Completed vs forming candle bookkeeping for the live chart.
 *
 * Pure helpers with no DOM access so they can be unit-tested under Node
 * (tests/js/candle-utils.test.cjs) and reused by app.js in the browser.
 *
 * Rules enforced here:
 * - Forming (incomplete) candles never enter the completed list.
 * - A refresh updates the forming candle in place — it is never appended.
 * - A provider-confirmed completed candle (`completed_tail`) is appended
 *   exactly once per timeframe boundary; the caller then full-reloads to
 *   recompute indicators for the promoted bar.
 * - If the confirmed tail is more than one full interval ahead of the last
 *   known candle, the caller is told to reload rather than render a gap.
 */
(function (root, factory) {
  const api = factory();
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  root.QuantPilotCandles = api;
})(typeof self !== "undefined" ? self : globalThis, function () {
  function ts(candle) {
    const value = candle && candle.timestamp ? new Date(candle.timestamp).getTime() : NaN;
    return Number.isFinite(value) ? value : NaN;
  }

  function normalizeCandle(raw) {
    if (!raw || typeof raw !== "object") return null;
    const t = ts(raw);
    const open = Number(raw.open), high = Number(raw.high), low = Number(raw.low), close = Number(raw.close);
    if (!Number.isFinite(t) || ![open, high, low, close].every(Number.isFinite)) return null;
    return {
      ...raw,
      timestamp: new Date(t).toISOString().replace(/\.000Z$/, "Z"),
      open, high, low, close,
      volume: Number.isFinite(Number(raw.volume)) ? Number(raw.volume) : 0,
      complete: raw.complete !== false,
    };
  }

  function applyCandleUpdate(candles, forming, update, intervalMs) {
    const next = Array.isArray(candles) ? candles.slice() : [];
    const lastTs = next.length ? ts(next[next.length - 1]) : -Infinity;
    const safeInterval = Number.isFinite(intervalMs) && intervalMs > 0 ? intervalMs : 3600000;

    // 1) Is the provider confirming a newly completed candle?
    const tail = normalizeCandle(update && update.completed_tail);
    if (tail) {
      const tailTs = ts(tail);
      if (lastTs === -Infinity || tailTs > lastTs) {
        const gap = lastTs !== -Infinity && tailTs - lastTs > safeInterval * 1.5;
        const formingTs = ts(forming);
        const incoming = normalizeCandle(update && update.forming);
        const newForming = incoming && ts(incoming) > tailTs ? incoming : (incoming || (formingTs > tailTs ? forming : null));
        return { candles: next.concat([{ ...tail, complete: true }]), forming: newForming, promoted: true, gap };
      }
    }

    // 2) Steady state: update (or drop) the forming candle in place.
    const incoming = normalizeCandle(update && update.forming);
    if (!incoming) {
      // Market closed or provider returned no forming candle.
      return { candles: next, forming: null, promoted: false, gap: false };
    }
    return { candles: next, forming: incoming, promoted: false, gap: false };
  }

  return { applyCandleUpdate, normalizeCandle, _ts: ts };
});
