"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");
const QU = require(path.join(__dirname, "..", "..", "public", "candle-utils.js"));

const C = (ts, close, complete = true) => ({ timestamp: ts, open: close - 1, high: close + 1, low: close - 2, close, volume: 100, complete });
const F = (ts, close) => C(ts, close, false);
const H1 = 3600000;

test("normalizeCandle rejects malformed input instead of inventing values", () => {
  assert.equal(QU.normalizeCandle(null), null);
  assert.equal(QU.normalizeCandle({ timestamp: "not-a-date", open: 1, high: 2, low: 1, close: 2 }), null);
  assert.equal(QU.normalizeCandle({ timestamp: "2026-11-09T06:00:00Z", open: "x", high: 2, low: 1, close: 2 }), null);
  const c = QU.normalizeCandle({ timestamp: "2026-11-09T06:00:00.123Z", open: "1.1", high: "1.2", low: "1.0", close: "1.15", volume: "50", complete: false });
  assert.equal(c.open, 1.1);
  assert.equal(c.complete, false);
  assert.equal(c.timestamp, "2026-11-09T06:00:00.123Z");
});

test("forming candle refresh updates in place and never duplicates", () => {
  const candles = [C("2026-11-09T05:00:00Z", 100), C("2026-11-09T06:00:00Z", 101)];
  let forming = F("2026-11-09T06:00:00Z", 102);
  for (const ts of ["t1", "t2", "t3"]) {
    const update = { forming: F("2026-11-09T06:00:00Z", 102 + Math.random()), completed_tail: C("2026-11-09T05:00:00Z", 100) };
    const result = QU.applyCandleUpdate(candles, forming, update, H1);
    assert.equal(result.candles.length, 2, "completed list unchanged on in-place forming update");
    assert.equal(result.forming.complete, false);
    forming = result.forming;
  }
});

test("forming candle is never appended to the completed list", () => {
  const candles = [C("2026-11-09T05:00:00Z", 100)];
  const result = QU.applyCandleUpdate(candles, null, { forming: F("2026-11-09T06:00:00Z", 103), completed_tail: C("2026-11-09T05:00:00Z", 100) }, H1);
  assert.equal(result.candles.length, 1);
  assert.equal(result.forming.close, 103);
});

test("provider-confirmed completed tail is appended exactly once per boundary", () => {
  let candles = [C("2026-11-09T05:00:00Z", 100)];
  let forming = F("2026-11-09T06:00:00Z", 102);
  const boundary = { forming: F("2026-11-09T07:00:00Z", 103), completed_tail: C("2026-11-09T06:00:00Z", 102) };
  const first = QU.applyCandleUpdate(candles, forming, boundary, H1);
  assert.equal(first.promoted, true);
  assert.equal(first.gap, false);
  assert.deepEqual(first.candles.map(c => c.timestamp), ["2026-11-09T05:00:00Z", "2026-11-09T06:00:00Z"]);
  assert.equal(first.candles[1].complete, true);
  assert.equal(first.forming.timestamp, "2026-11-09T07:00:00Z");
  // Second poll with the same payload must NOT append again.
  const second = QU.applyCandleUpdate(first.candles, first.forming, boundary, H1);
  assert.equal(second.promoted, false);
  assert.equal(second.candles.length, 2);
});

test("a confirmed tail more than one interval ahead signals a gap reload", () => {
  const candles = [C("2026-11-09T05:00:00Z", 100)];
  const result = QU.applyCandleUpdate(candles, null, { forming: null, completed_tail: C("2026-11-09T09:00:00Z", 110) }, H1);
  assert.equal(result.promoted, true);
  assert.equal(result.gap, true);
});

test("market closure (no forming candle) keeps confirmed candles intact", () => {
  const candles = [C("2026-11-09T05:00:00Z", 100), C("2026-11-09T06:00:00Z", 101)];
  const result = QU.applyCandleUpdate(candles, F("2026-11-09T06:00:00Z", 102), { forming: null, completed_tail: null }, H1);
  assert.equal(result.forming, null);
  assert.equal(result.candles.length, 2);
});

test("malformed update payload keeps prior confirmed state", () => {
  const candles = [C("2026-11-09T05:00:00Z", 100)];
  const result = QU.applyCandleUpdate(candles, null, { forming: { timestamp: "junk" }, completed_tail: { timestamp: "junk" } }, H1);
  assert.equal(result.candles.length, 1);
  assert.equal(result.forming, null);
});
