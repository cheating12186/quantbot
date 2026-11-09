"use strict";

const state = { page: "overview", market: null, quote: null, report: null, backtest: null, integrations: null, quoteSymbol: "EUR_USD", forming: null, candleTimer: null, formingPoll: { running: false } };
const CANDLE_POLL_MS = Number(window.QUANTPILOT_CANDLE_POLL_MS) || 8000; // live forming-candle refresh (5–10s)
const TIMEFRAME_MS = { "5m": 300000, "15m": 900000, "1h": 3600000, "1d": 86400000 };
const content = document.getElementById("content");
const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

async function api(path, options = {}) {
  const config = { headers: { "Content-Type": "application/json", ...(options.headers || {}) }, ...options };
  const response = await fetch(path, config);
  const text = await response.text();
  let data;
  try { data = text ? JSON.parse(text) : {}; } catch { data = { detail: text || `HTTP ${response.status}` }; }
  if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail || data));
  return data;
}
const esc = value => String(value ?? "").replace(/[&<>'"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[c]));
const num = (value, digits = 2) => value === null || value === undefined || !Number.isFinite(Number(value)) ? "—" : Number(value).toLocaleString(undefined, { maximumFractionDigits: digits, minimumFractionDigits: digits });
const money = value => value === null || value === undefined ? "—" : `${Number(value) < 0 ? "−" : ""}$${Math.abs(Number(value)).toLocaleString(undefined, { maximumFractionDigits: 2, minimumFractionDigits: 2 })}`;
const pct = (value, digits = 2) => Number.isFinite(Number(value)) ? `${(Number(value) * 100).toFixed(digits)}%` : "—";
const dateFmt = value => value ? new Date(value).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "—";
const price = value => Number(value) >= 100 ? num(value, 2) : num(value, 5);
const signed = value => `<span class="${Number(value) >= 0 ? "positive" : "negative"}">${money(value)}</span>`;
function toast(message, error = false) { const el = $("#toast"); el.textContent = message; el.className = `toast show${error ? " error" : ""}`; clearTimeout(toast.timer); toast.timer = setTimeout(() => el.className = "toast", 4500); }
function loading(text = "Loading live data…") { return `<div class="loading-screen"><div class="spinner"></div><p>${esc(text)}</p></div>`; }
function head(title, subtitle, action = "") { return `<div class="page-head"><div><h1>${title}</h1><p>${subtitle}</p></div><div class="page-actions">${action}</div></div>`; }
function metric(label, value, sub = "", cls = "") { return `<div class="card"><div class="metric-label">${label}</div><div class="metric-value ${cls}">${value}</div>${sub ? `<div class="metric-sub">${sub}</div>` : ""}</div>`; }
function badge(value) { const v = String(value || "UNKNOWN"); return `<span class="badge ${v.toLowerCase()}">${esc(v)}</span>`; }
function provenance(label, detail, kind = "") { return `<div class="provenance ${kind}"><b>${label}</b><span>${detail}</span></div>`; }
function table(rows, columns, empty = "No records") {
  if (!rows || !rows.length) return `<div class="empty">${empty}</div>`;
  return `<div class="table-wrap"><table><thead><tr>${columns.map(c => `<th>${c.label}</th>`).join("")}</tr></thead><tbody>${rows.map(row => `<tr>${columns.map(c => `<td>${c.render ? c.render(row) : esc(row[c.key])}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
}
function jsonBlock(value) { return `<pre class="json">${esc(JSON.stringify(value, null, 2))}</pre>`; }
function pnlClass(value) { return Number(value) >= 0 ? "positive" : "negative"; }

function lineChart(labels, series, options = {}) {
  if (!labels?.length || !series?.length) return `<div class="empty">Insufficient data for chart</div>`;
  const W = 920, H = options.height || 320, pad = { l: 66, r: 20, t: 20, b: 38 };
  const all = series.flatMap(s => s.values.filter(Number.isFinite));
  let min = Math.min(...all), max = Math.max(...all);
  const padding = Math.max((max - min) * .1, Math.abs(max || 1) * .001); min -= padding; max += padding;
  const x = i => pad.l + (labels.length === 1 ? (W - pad.l - pad.r) / 2 : i / (labels.length - 1) * (W - pad.l - pad.r));
  const y = v => pad.t + (max - v) / (max - min || 1) * (H - pad.t - pad.b);
  let svg = `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Financial line chart">`;
  for (let i = 0; i <= 5; i++) { const yy = pad.t + i / 5 * (H - pad.t - pad.b), value = max - i / 5 * (max - min); svg += `<line class="gridline" x1="${pad.l}" y1="${yy}" x2="${W-pad.r}" y2="${yy}"/><text x="${pad.l-9}" y="${yy+3}" text-anchor="end">${options.percent ? value.toFixed(1)+"%" : num(value, Math.abs(max)<10?4:0)}</text>`; }
  const ticks = 5;
  for (let i = 0; i <= ticks; i++) { const index = Math.min(labels.length - 1, Math.round(i / ticks * (labels.length - 1))); const d = new Date(labels[index]); svg += `<text x="${x(index)}" y="${H-10}" text-anchor="middle">${esc(d.toLocaleDateString([], {month:"short",day:"numeric"}))}</text>`; }
  series.forEach(s => {
    const points = s.values.map((v, i) => Number.isFinite(v) ? `${x(i).toFixed(2)},${y(v).toFixed(2)}` : null).filter(Boolean);
    if (!points.length) return;
    if (s.area) { const base = y(min); svg += `<polygon points="${pad.l},${base} ${points.join(" ")} ${x(s.values.length-1)},${base}" fill="${s.color}" class="area"/>`; }
    svg += `<polyline class="line" points="${points.join(" ")}" stroke="${s.color}" ${s.dash ? 'stroke-dasharray="6 5"' : ""}/>`;
  });
  return svg + "</svg>" + `<div class="chart-legend">${series.map(s => `<span><i class="legend-dot" style="background:${s.color}"></i>${esc(s.name)}</span>`).join("")}</div>`;
}

function candleChart(candles, forming) {
  const confirmed = (candles || []).slice(-110);
  const live = forming && Number.isFinite(new Date(forming.timestamp).getTime()) ? { ...forming, complete: false } : null;
  const data = live ? [...confirmed.slice(-109), live] : confirmed;
  if (!data.length) return `<div class="empty">No candle data</div>`;
  const W=1000,H=430,pad={l:66,r:18,t:18,b:36},priceBottom=300,volTop=330,volBottom=385;
  const values = data.flatMap(d => [d.high,d.low,d.ema_50].filter(Number.isFinite));
  let min=Math.min(...values),max=Math.max(...values); const buffer=(max-min)*.06||1;min-=buffer;max+=buffer;
  const x=i=>pad.l+(i+.5)/data.length*(W-pad.l-pad.r), y=v=>pad.t+(max-v)/(max-min)*(priceBottom-pad.t);
  const cw=Math.max(2,(W-pad.l-pad.r)/data.length*.62),maxVol=Math.max(...data.map(d=>d.volume||0),1);
  let svg=`<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Candlestick chart with EMA indicators">`;
  for(let i=0;i<=5;i++){const yy=pad.t+i/5*(priceBottom-pad.t),v=max-i/5*(max-min);svg+=`<line class="gridline" x1="${pad.l}" y1="${yy}" x2="${W-pad.r}" y2="${yy}"/><text x="${pad.l-8}" y="${yy+3}" text-anchor="end">${price(v)}</text>`;}
  data.forEach((d,i)=>{const forming=d.complete===false,up=d.close>=d.open,color=up?"#34d399":"#fb7185",xx=x(i);svg+=`<line x1="${xx}" y1="${y(d.high)}" x2="${xx}" y2="${y(d.low)}" stroke="${color}" stroke-width="1.4"${forming?' stroke-dasharray="3 2"':""}/><rect x="${xx-cw/2}" y="${y(Math.max(d.open,d.close))}" width="${cw}" height="${Math.max(1,Math.abs(y(d.open)-y(d.close)))}" fill="${color}"${forming?' fill-opacity="0.28" stroke="'+color+'" stroke-width="1.3" stroke-dasharray="4 3"':""}/><rect x="${xx-cw/2}" y="${volBottom-(d.volume||0)/maxVol*(volBottom-volTop)}" width="${cw}" height="${(d.volume||0)/maxVol*(volBottom-volTop)}" fill="#3b82f6" opacity="${forming?"0.25":".45"}"/>`;});
  [{key:"ema_9",color:"#60a5fa"},{key:"ema_15",color:"#c084fc"},{key:"ema_50",color:"#fbbf24"}].forEach(s=>{const points=data.map((d,i)=>Number.isFinite(d[s.key])?`${x(i)},${y(d[s.key])}`:null).filter(Boolean);svg+=`<polyline class="line" points="${points.join(" ")}" stroke="${s.color}" stroke-width="1.3"/>`;});
  for(let i=0;i<=5;i++){const index=Math.min(data.length-1,Math.round(i/5*(data.length-1))),d=new Date(data[index].timestamp);svg+=`<text x="${x(index)}" y="${H-9}" text-anchor="middle">${esc(d.toLocaleDateString([], {month:"short",day:"numeric"}))}</text>`;}
  return svg+"</svg>"+`<div class="chart-legend"><span><i class="legend-dot" style="background:#60a5fa"></i>EMA 9</span><span><i class="legend-dot" style="background:#c084fc"></i>EMA 15</span><span><i class="legend-dot" style="background:#fbbf24"></i>EMA 50</span><span><i class="legend-dot" style="background:#3b82f6"></i>Volume</span>${live?'<span><i class="legend-dot forming-dot"></i>Forming candle (unconfirmed, chart-only)</span>':''}</div>`;
}

async function loadIntegrations() {
  try {
    state.integrations = await api("/api/v1/market/integrations");
    const o = state.integrations.oanda, g = state.integrations.groq;
    $("#oanda-status").textContent = o.configured ? "PRACTICE ONLINE" : "NOT CONFIGURED";
    $("#oanda-status").classList.toggle("online", o.configured);
    $("#groq-status").textContent = g.configured ? g.selected_model : "DETERMINISTIC";
    $("#groq-status").classList.toggle("online", g.configured);
    $("#db-status").textContent = state.integrations.database === "PERSISTENT" ? "POSTGRES" : "EPHEMERAL";
    $("#db-status").classList.toggle("online", state.integrations.database === "PERSISTENT");
  } catch (error) { $("#oanda-status").textContent = "API OFFLINE"; console.error(error); }
}
async function loadQuote(symbol = state.quoteSymbol) {
  try {
    const quote = await api(`/api/v1/market/quote/${encodeURIComponent(symbol)}`);
    state.quote = quote; state.quoteSymbol = symbol;
    $("#top-symbol").textContent = symbol.replace("_", "/");
    $("#top-quote").textContent = price(quote.mid);
    $("#top-quote-time").textContent = `bid ${price(quote.bid)} · ask ${price(quote.ask)}`;
    const target = $("#live-quote");
    if (target) target.innerHTML = quoteCards(quote);
  } catch (error) {
    $("#top-quote").textContent = "—"; $("#top-quote-time").textContent = "quote unavailable";
    const target = $("#live-quote");
    if (target) target.innerHTML = `<div class="alert error">Quote unavailable · ${esc(error.message)}</div>`;
  }
}
function quoteCards(q) { return `<div class="quote-cell"><span>Mid price</span><strong>${price(q.mid)}</strong></div><div class="quote-cell"><span>Bid</span><strong>${price(q.bid)}</strong></div><div class="quote-cell"><span>Ask</span><strong>${price(q.ask)}</strong></div><div class="quote-cell"><span>Spread</span><strong>${price(q.spread)}</strong></div>`; }

function navigate(page) {
  state.page = page;
  $$(".nav-item").forEach(button => button.classList.toggle("active", button.dataset.page === page));
  $("#sidebar").classList.remove("open");
  ({ overview: renderOverview, research: renderResearch, assistant: renderAssistant, trading: renderTrading, risk: renderRisk, backtesting: renderBacktesting, monitoring: renderMonitoring }[page] || renderOverview)();
}

async function renderOverview() {
  content.innerHTML = head("Command center", "OANDA practice market intelligence, paper account, risk posture, and agent activity") + loading();
  try {
    const [p, fills, runs, equity] = await Promise.all([api("/api/v1/paper/portfolio"), api("/api/v1/paper/fills"), api("/api/v1/research/runs"), api("/api/v1/paper/equity")]);
    const history = equity.slice(-200);
    content.innerHTML = head("Command center", "OANDA practice market intelligence, paper account, risk posture, and agent activity") +
      `<div class="grid grid-5">${metric("Account equity",money(p.equity),pct(p.equity/p.initial_equity-1),pnlClass(p.equity-p.initial_equity))}${metric("Buying power",money(p.buying_power),"Available simulated capital")}${metric("Daily P&L",signed(p.daily_pnl),"Mark-to-market",pnlClass(p.daily_pnl))}${metric("Open positions",p.open_positions.length,`Max ${state.integrations?.database||"demo"} portfolio`)}${metric("Drawdown",pct(p.drawdown_pct),`HWM ${money(p.high_water_mark)}`,p.drawdown_pct>.04?"negative":"")}</div>` +
      provenance("SIMULATED PAPER ACCOUNT",`Balances are independent of OANDA. Storage: ${state.integrations?.database||"unknown"}. No real-money orders exist.`,"paper") +
      `<div class="grid grid-2 mt"><div class="card"><h3 class="section-title">Paper equity trajectory</h3>${lineChart(history.map(x=>x.timestamp),[{name:"Equity",values:history.map(x=>x.equity),color:"#60a5fa",area:true}])}</div><div class="card"><h3 class="section-title">Exposure & protection</h3>${riskBar("Gross exposure",p.gross_exposure_pct,1)}${riskBar("Open portfolio risk",p.portfolio_risk_pct,.03)}<div class="mt">${p.trading_halted?`<div class="alert error">TRADING HALTED · ${esc(p.halt_reasons.join(", "))}</div>`:`<div class="alert success">Risk controls armed · new entries permitted</div>`}</div><div class="mt" id="live-quote">${state.quote?quoteCards(state.quote):`<div class="empty">Loading OANDA practice quote…</div>`}</div></div></div>` +
      `<div class="grid grid-2 mt"><div class="card"><h3 class="section-title">Open positions</h3>${positionTable(p.open_positions)}</div><div class="card"><h3 class="section-title">Recent agent decisions</h3>${runTable(runs.slice(0,7))}</div></div>` +
      `<div class="card mt"><h3 class="section-title">Recent simulated executions</h3>${fillTable(fills.slice(0,8))}</div>`;
    loadQuote();
  } catch (error) { content.innerHTML += `<div class="alert error">${esc(error.message)}</div>`; }
}
function riskBar(label, value, max) { return `<div class="risk-row"><div class="split"><span>${label}</span><b>${pct(value)}</b></div><div class="progress"><div style="width:${Math.min(100,value/max*100)}%;background:${value>=max?"#fb7185":"#60a5fa"}"></div></div></div>`; }
function positionTable(rows) { return table(rows,[{key:"symbol",label:"Instrument"},{key:"side",label:"Side",render:r=>badge(r.side)},{key:"quantity",label:"Quantity",render:r=>num(r.quantity,2)},{key:"entry_price",label:"Entry",render:r=>price(r.entry_price)},{key:"mark_price",label:"Mark",render:r=>price(r.mark_price)},{key:"stop_loss",label:"Stop",render:r=>price(r.stop_loss)},{key:"take_profit",label:"Target",render:r=>price(r.take_profit)}],"No open paper positions"); }
function runTable(rows) { return table(rows,[{key:"created_at",label:"Time",render:r=>dateFmt(r.created_at)},{key:"ticker",label:"Instrument"},{key:"timeframe",label:"TF"},{key:"outcome",label:"Decision",render:r=>badge(r.outcome)},{key:"run_id",label:"",render:r=>`<button class="button small" onclick="inspectRun('${r.run_id}')">Inspect</button>`}],"No agent decisions yet"); }
function fillTable(rows) { return table(rows,[{key:"timestamp",label:"Time",render:r=>dateFmt(r.timestamp)},{key:"symbol",label:"Instrument"},{key:"side",label:"Side"},{key:"quantity",label:"Qty",render:r=>num(r.quantity,2)},{key:"price",label:"Fill",render:r=>price(r.price)},{key:"fees",label:"Fees",render:r=>money(r.fees)},{key:"reason",label:"Reason"}],"No simulated executions"); }

function researchForm() { return `<div class="card mb"><form id="market-form" class="form-grid"><div class="field"><label>Instrument</label><input name="symbol" value="${esc(state.market?.request?.symbol||"EUR_USD")}" placeholder="EUR_USD" required></div><div class="field"><label>Timeframe</label><select name="timeframe">${["5m","15m","1h","1d"].map(x=>`<option ${x===(state.market?.request?.timeframe||"1d")?"selected":""}>${x}</option>`).join("")}</select></div><div class="field"><label>Completed bars</label><input name="rows" type="number" min="60" max="1000" value="300"></div><div class="field"><label>&nbsp;</label><button class="button primary" type="submit">Analyze market</button></div></form></div>`; }
async function renderResearch() {
  content.innerHTML = head("Market research", "Provider-labelled market quotes, completed OHLCV candles, and Python-calculated indicators") + researchForm() + `<div id="market-results">${state.market?marketResults(state.market):loading("Retrieving completed market candles…")}</div>`;
  $("#market-form").onsubmit = event => { event.preventDefault(); const f=new FormData(event.target); loadMarket(f.get("symbol"),f.get("timeframe"),f.get("rows")); };
  if (!state.market) loadMarket("EUR_USD","1d",300); else { loadQuote(state.market.request.symbol); startFormingPoll(); }
}
async function loadMarket(symbol,timeframe,rows) {
  const target=$("#market-results"); if(target)target.innerHTML=loading("Retrieving completed candles and current quote…");
  try {
    const data=await api(`/api/v1/market/candles/${encodeURIComponent(symbol)}?timeframe=${timeframe}&rows=${rows}`);
    state.market={...data,request:{symbol:symbol.toUpperCase(),timeframe,rows}};
    state.forming=data.forming_candle||null;
    state.quoteSymbol=symbol.toUpperCase();
    if($("#market-results"))$("#market-results").innerHTML=marketResults(state.market);
    startFormingPoll();
    loadQuote(symbol.toUpperCase());
  } catch(error){ if(target)target.innerHTML=`<div class="alert error">Market retrieval failed: ${esc(error.message)}</div>`; }
}
function formingStatusText() {
  if (state.forming) return `Forming candle · ${dateFmt(state.forming.timestamp)} — unconfirmed, chart-only · refreshing every ${Math.round(CANDLE_POLL_MS / 1000)}s · not used for decisions`;
  return "No forming candle right now (market closed or provider delay) — showing confirmed completed candles only";
}
function setFormingStatus(text, isError=false) { const el=$("#forming-status"); if(el){ el.textContent=text; el.style.color=isError?"#fbbf24":""; } }
function startFormingPoll() { clearInterval(state.candleTimer); state.candleTimer=setInterval(refreshFormingCandle, CANDLE_POLL_MS); }
function stopFormingPoll() { clearInterval(state.candleTimer); state.candleTimer=null; }
async function refreshFormingCandle() {
  const chartEl=$("#market-chart");
  if(!chartEl || !state.market?.request) { stopFormingPoll(); return; }
  if(state.formingPoll.running) return;
  state.formingPoll.running=true;
  const { symbol, timeframe, rows } = state.market.request;
  try {
    const payload=await api(`/api/v1/market/candles/${encodeURIComponent(symbol)}/forming?timeframe=${encodeURIComponent(timeframe)}`);
    const intervalMs=TIMEFRAME_MS[timeframe]||3600000;
    const result=window.QuantPilotCandles.applyCandleUpdate(state.market.candles, state.forming, payload, intervalMs);
    if(result.gap){ setFormingStatus("Live data moved ahead — reloading confirmed candles…"); loadMarket(symbol,timeframe,rows); return; }
    state.market.candles=result.candles;
    state.forming=result.forming;
    if(result.promoted){ loadMarket(symbol,timeframe,rows); return; } // boundary crossed: refetch to recompute indicators for the promoted bar
    chartEl.innerHTML=candleChart(state.market.candles, state.forming);
    setFormingStatus(formingStatusText());
  } catch(error) {
    setFormingStatus(`Live update failed (${error.message}) — showing last confirmed candles`, true);
  } finally {
    state.formingPoll.running=false;
  }
}
function marketResults(data) {
  const d=data.dataset,c=data.candles,last=c[c.length-1],q=state.quote&&state.quote.instrument===d.metadata.instrument?state.quote:null;
  const provenanceLabel=d.is_synthetic?"SYNTHETIC DATA":d.source==="oanda"?"ACTUAL OANDA PRACTICE DATA":`ACTUAL ${String(d.source).toUpperCase()} DATA`;
  const sourceDetail=`${d.source} · ${d.rows} completed bars · latest ${dateFmt(d.data_timestamp)} · market data is read-only`;
  const disclosures=(d.quality.issues||[]).map(issue=>`<div class="alert ${issue.fatal?"error":""}"><b>${esc(issue.code)}</b> · ${esc(issue.message)}</div>`).join("");
  return provenance(provenanceLabel,sourceDetail,"python")+disclosures+
  `<div class="grid grid-4">${metric("Instrument",d.metadata.instrument||d.symbol,d.source==="oanda"?"OANDA practice":d.source)}${metric("Last completed close",price(last.close),dateFmt(last.timestamp))}${metric("RSI · ATR",`${num(last.rsi_14,1)} · ${price(last.atr_14)}`,"Python indicators")}${metric("Relative volume",num(last.relative_volume,2),"Current vs prior 20-bar mean")}</div><div class="card mt"><div class="split"><h3 class="section-title">Price, EMA trend &amp; volume</h3>${badge(d.quality.valid?"VALIDATED":"DATA WARNING")}</div><div id="market-chart">${candleChart(c, state.forming)}</div><div class="metric-sub" id="forming-status">${esc(formingStatusText())}</div></div><div class="grid grid-2 mt"><div class="card"><h3 class="section-title">${d.source==="oanda"?"Live practice quote":"Provider quote status"}</h3><div id="live-quote">${q?quoteCards(q):loading("Polling current quote…")}</div><div class="metric-sub">Quote timestamp: ${q?dateFmt(q.timestamp):"waiting"}</div></div><div class="card"><h3 class="section-title">Latest numerical evidence</h3>${table([{name:"EMA 9 / 15",value:`${price(last.ema_9)} / ${price(last.ema_15)}`},{name:"EMA 50 / 200",value:`${price(last.ema_50)} / ${price(last.ema_200)}`},{name:"MACD histogram",value:num(last.macd_hist,6)},{name:"Bollinger width",value:last.bb_upper&&last.bb_lower?price(last.bb_upper-last.bb_lower):"—"},{name:"VWAP",value:price(last.vwap)}],[{key:"name",label:"Indicator"},{key:"value",label:"Python value"}])}<button class="button primary mt" onclick="prepareAssistant('${esc(d.symbol)}','${esc(data.request.timeframe)}')">Run multi-agent analysis ✦</button></div></div>`;
}
function prepareAssistant(symbol,timeframe){state.preset={symbol,timeframe};navigate("assistant");}

async function renderAssistant() {
  const preset=state.preset||{symbol:"EUR_USD",timeframe:"1d"};
  content.innerHTML=head("AI research assistant","Submit a forex objective, inspect every agent, and execute only through deterministic controls")+
  `<div class="card mb"><form id="agent-form" class="form-grid"><div class="field"><label>Instrument</label><input name="ticker" value="${esc(preset.symbol)}" required></div><div class="field"><label>Timeframe</label><select name="timeframe">${["5m","15m","1h","1d"].map(x=>`<option ${x===preset.timeframe?"selected":""}>${x}</option>`).join("")}</select></div><div class="field full"><label>Natural-language objective</label><textarea name="request">Analyze this forex pair for a high-quality EMA crossover setup. Reject the trade if any strategy, data-quality, or risk rule fails.</textarea></div><div class="field full row"><label class="check"><input type="checkbox" name="auto_execute"> Execute in the internal paper broker only if every check passes</label><button class="button primary" type="submit">Launch specialized agents ✦</button></div></form></div><div class="card mb"><div class="split"><div><h3 class="section-title">Autopilot · PAPER ONLY</h3><p class="section-subtitle">Re-runs the full agent chain every 60s while this tab is open, using the form values above. Any execution goes only to the simulated broker through the deterministic safety gate; stale data, failed checks, or a missing fresh crossover block every order. Weekday 08:00 UTC ticks also run server-side via Vercel Cron.</p></div><label class="check" style="white-space:nowrap"><input type="checkbox" id="autopilot-toggle"> Enabled</label></div><div class="metric-sub" id="autopilot-status">Off — no background agent cycle is running</div></div><div id="agent-results">${state.report?reportHTML(state.report):`<div class="empty">No research run in this browser session. Historical reports remain available in Agent Monitoring.</div>`}</div>`;
  $("#agent-form").onsubmit=runAgents;
  $("#autopilot-toggle").onchange=event=>{
    if(event.target.checked){state.autopilot=state.autopilot||{timer:null,running:false};autopilotTick();state.autopilot.timer=setInterval(autopilotTick,60000);setAutopilotStatus("Autopilot enabled — full agent cycle every 60s");}
    else{clearInterval(state.autopilot?.timer);if(state.autopilot)state.autopilot.timer=null;setAutopilotStatus("Off — no background agent cycle is running");}
  };
}
function setAutopilotStatus(text, isError=false){const el=$("#autopilot-status");if(el){el.textContent=text;el.style.color=isError?"#fb7185":"";}}
async function autopilotTick(){
  state.autopilot=state.autopilot||{timer:null,running:false};
  if(state.autopilot.running)return;
  if(!document.contains($("#autopilot-status"))){clearInterval(state.autopilot.timer);state.autopilot.timer=null;return;}
  const form=$("#agent-form");if(!form)return;
  const f=new FormData(form);
  state.autopilot.running=true;
  setAutopilotStatus(`Running full agent cycle at ${new Date().toLocaleTimeString()}…`);
  try{
    const body={ticker:f.get("ticker"),timeframe:f.get("timeframe"),request:f.get("request"),auto_execute:f.get("auto_execute")==="on",rows:300};
    const report=await api("/api/v1/research",{method:"POST",body:JSON.stringify(body)});
    state.report=report;
    if($("#agent-results")&&document.contains($("#agent-results"))){$("#agent-results").innerHTML=reportHTML(report);bindReportTabs();}
    setAutopilotStatus(`Last cycle ${new Date().toLocaleTimeString()} — ${report.outcome}`);
  }catch(error){setAutopilotStatus(`Cycle failed closed: ${error.message}`,true);}
  finally{state.autopilot.running=false;}
}
async function runAgents(event){  event.preventDefault();const form=event.target,f=new FormData(form),button=form.querySelector("button[type=submit]");button.disabled=true;
  const steps=["Validating request and connecting to OANDA practice…","Market Analyst and News Analyst working independently…","Auditing strategy, risk, sizing, and supervisor consistency…","Repeating every mandatory control in the safety engine…"];
  $("#agent-results").innerHTML=`<div class="card"><div class="row"><div class="spinner"></div><b>Coordinating QuantPilot agents</b></div><div class="mt">${steps.map((s,i)=>`<div class="step" id="step-${i}"><span class="step-dot"></span>${s}</div>`).join("")}</div></div>`;
  let i=0;const timer=setInterval(()=>{i=Math.min(i+1,steps.length-1);$$('.step').forEach((el,j)=>el.style.opacity=j<=i?"1":".35");},1800);
  try{const body={ticker:f.get("ticker"),timeframe:f.get("timeframe"),request:f.get("request"),auto_execute:f.get("auto_execute")==="on",rows:300};const report=await api("/api/v1/research",{method:"POST",body:JSON.stringify(body)});state.report=report;$("#agent-results").innerHTML=reportHTML(report);bindReportTabs();}
  catch(error){$("#agent-results").innerHTML=`<div class="alert error">Workflow failed closed: ${esc(error.message)}</div>`;}
  finally{clearInterval(timer);button.disabled=false;}
}
function reportHTML(r){
  return `<div class="card"><div class="split"><div><div class="eyebrow">FINAL DECISION</div><div class="mt">${badge(r.outcome)}</div></div><div class="row">${metric("Proposal quantity",r.proposal?num(r.proposal.quantity,2):"—")}${metric("Agents / tools",`${r.traces.length} / ${r.traces.reduce((a,t)=>a+t.tool_calls.length,0)}`,"Measured execution traces")}</div></div><ul class="reason-list">${r.reasons.map(x=>`<li>${esc(x)}</li>`).join("")}</ul>${provenance("PYTHON METRICS","Indicators, confidence, risk, sizing, rules, and safety are deterministic.","python")}${provenance("LLM STATUS",r.supervisor?.review_source||"No LLM interpretation used","llm")}${provenance("PAPER EXECUTION",r.execution?.message||"No execution attempted","paper")}</div>
  <div class="tabs">${["Timeline","Market","Rules","Risk & sizing","Supervisor & safety","News","Raw report"].map((x,i)=>`<button class="tab ${i===0?"active":""}" data-tab="${i}">${x}</button>`).join("")}</div>
  <div class="tab-panel" data-panel="0">${traceHTML(r.traces)}</div><div class="tab-panel" data-panel="1" hidden>${jsonBlock(r.market)}</div><div class="tab-panel" data-panel="2" hidden>${jsonBlock(r.rules)}</div><div class="tab-panel" data-panel="3" hidden><div class="grid grid-2">${jsonBlock(r.risk)}${jsonBlock(r.money)}</div></div><div class="tab-panel" data-panel="4" hidden><div class="grid grid-2">${jsonBlock(r.supervisor)}${jsonBlock(r.safety)}</div></div><div class="tab-panel" data-panel="5" hidden>${jsonBlock(r.news)}</div><div class="tab-panel" data-panel="6" hidden>${jsonBlock(r)}</div>`;
}
function traceHTML(traces){return table(traces,[{key:"agent",label:"Agent"},{key:"status",label:"Status",render:r=>badge(r.status)},{key:"duration_ms",label:"Duration",render:r=>num(r.duration_ms,1)+" ms"},{key:"tool_calls",label:"Tools",render:r=>r.tool_calls.length},{key:"input_tokens",label:"Tokens",render:r=>(r.input_tokens||0)+(r.output_tokens||0)},{key:"error",label:"Error",render:r=>esc(r.error||"—")}])+traces.map(t=>`<details class="trace"><summary>${esc(t.agent)} · ${esc(t.status)} · ${num(t.duration_ms,1)} ms</summary><div class="trace-body">${t.tool_calls.map(c=>`<div class="tool-log">${esc(c.tool)} [${esc(c.status)}] ${num(c.duration_ms,2)}ms\nIN: ${esc(c.input_summary)}\nOUT: ${esc(c.output_summary)}\nERROR: ${esc(c.error||"none")}</div>`).join("")||"No tool calls"}</div></details>`).join("");}
function bindReportTabs(){$$(".tab").forEach(tab=>tab.onclick=()=>{$$(".tab").forEach(x=>x.classList.toggle("active",x===tab));$$(".tab-panel").forEach(panel=>panel.hidden=panel.dataset.panel!==tab.dataset.tab);});}

async function renderTrading(){
  content.innerHTML=head("Paper trading","Internal simulated positions, orders, protective exits, and execution history")+loading();
  try{const[p,orders,fills]=await Promise.all([api("/api/v1/paper/portfolio"),api("/api/v1/paper/orders"),api("/api/v1/paper/fills")]);
    content.innerHTML=head("Paper trading","Internal simulated positions, orders, protective exits, and execution history")+provenance("SIMULATED EXECUTIONS","OANDA supplies data only. Fills include modelled fees and slippage; no OANDA orders are submitted.","paper")+
    `<div class="grid grid-4">${metric("Cash",money(p.cash))}${metric("Realized P&L",signed(p.realized_pnl),"Entry and exit fees included",pnlClass(p.realized_pnl))}${metric("Unrealized P&L",signed(p.unrealized_pnl),"Current marks",pnlClass(p.unrealized_pnl))}${metric("Pending orders",orders.filter(o=>o.status==="PENDING").length)}</div><div class="card mt"><h3 class="section-title">Open positions & partial closes</h3>${positionTable(p.open_positions)}${p.open_positions.length?closeForm(p.open_positions):""}</div><div class="card mt"><h3 class="section-title">Pending orders</h3>${orderTable(orders.filter(o=>o.status==="PENDING"))}</div><div class="card mt"><h3 class="section-title">Execution history</h3>${fillTable(fills)}</div><div class="card mt"><h3 class="section-title">All orders</h3>${orderTable(orders)}</div><div class="card mt"><h3 class="section-title">Candle replay</h3><p class="section-subtitle">Replay OHLC through pending limits and protective exits. Stop-loss wins ambiguous bars.</p>${candleForm()}</div>`;
    const cf=$("#close-form");if(cf)cf.onsubmit=closePosition;$$('[data-cancel]').forEach(b=>b.onclick=()=>cancelOrder(b.dataset.cancel));$("#candle-form").onsubmit=replayCandle;
  }catch(error){content.innerHTML+=`<div class="alert error">${esc(error.message)}</div>`;}
}
function closeForm(positions){return `<form id="close-form" class="form-grid mt"><div class="field"><label>Position</label><select name="symbol">${positions.map(p=>`<option value="${p.symbol}" data-max="${p.quantity}" data-price="${p.mark_price}">${p.symbol} · ${p.side} ${p.quantity}</option>`).join("")}</select></div><div class="field"><label>Quantity</label><input name="quantity" type="number" step="any" min="0.000001" value="${positions[0].quantity}"></div><div class="field"><label>Reference price</label><input name="market_price" type="number" step="any" value="${positions[0].mark_price}"></div><div class="field"><label>&nbsp;</label><button class="button danger">Close paper position</button></div></form>`;}
function orderTable(rows){return table(rows,[{key:"created_at",label:"Created",render:r=>dateFmt(r.created_at)},{key:"symbol",label:"Instrument"},{key:"side",label:"Side"},{key:"order_type",label:"Type"},{key:"quantity",label:"Qty",render:r=>num(r.quantity,2)},{key:"status",label:"Status",render:r=>badge(r.status)},{key:"average_fill_price",label:"Avg fill",render:r=>price(r.average_fill_price)},{key:"order_id",label:"Action",render:r=>r.status==="PENDING"?`<button class="button small danger" data-cancel="${r.order_id}">Cancel</button>`:"—"}],"No orders");}
function candleForm(){return `<form id="candle-form" class="form-grid"><div class="field"><label>Instrument</label><input name="symbol" value="EUR_USD"></div><div class="field"><label>Open</label><input name="open" type="number" step="any" value="1.1000"></div><div class="field"><label>High</label><input name="high" type="number" step="any" value="1.1020"></div><div class="field"><label>Low</label><input name="low" type="number" step="any" value="1.0980"></div><div class="field"><label>Close</label><input name="close" type="number" step="any" value="1.1010"></div><div class="field"><label>&nbsp;</label><button class="button">Process paper candle</button></div></form><div id="replay-result"></div>`;}
async function closePosition(event){event.preventDefault();const f=new FormData(event.target),symbol=f.get("symbol");try{const fill=await api(`/api/v1/paper/positions/${symbol}/close`,{method:"POST",body:JSON.stringify({quantity:Number(f.get("quantity")),market_price:Number(f.get("market_price"))})});toast(`Paper close filled at ${price(fill.price)}`);renderTrading();}catch(error){toast(error.message,true);}}
async function cancelOrder(id){try{await api(`/api/v1/paper/orders/${id}`,{method:"DELETE"});toast("Pending order cancelled");renderTrading();}catch(error){toast(error.message,true);}}
async function replayCandle(event){event.preventDefault();const f=new FormData(event.target),body=Object.fromEntries(f.entries());["open","high","low","close"].forEach(k=>body[k]=Number(body[k]));try{const fills=await api("/api/v1/paper/candles",{method:"POST",body:JSON.stringify(body)});$("#replay-result").innerHTML=`<div class="alert success">Processed candle · ${fills.length} fill(s)</div>${jsonBlock(fills)}`;}catch(error){toast(error.message,true);}}

async function renderRisk(){content.innerHTML=head("Risk management","Independent capital controls, exposure, loss limits, and trading-halt status")+loading();try{const[p,config]=await Promise.all([api("/api/v1/paper/portfolio"),api("/api/v1/paper/risk/config")]);content.innerHTML=head("Risk management","Independent capital controls, exposure, loss limits, and trading-halt status")+(p.trading_halted?`<div class="alert error">HARD TRADING HALT · ${esc(p.halt_reasons.join(", "))}</div>`:`<div class="alert success">No hard risk breach · deterministic safety gate active</div>`)+provenance("PYTHON RISK ENGINE","Limits are loaded from YAML and rechecked before every simulated execution.","python")+`<div class="grid grid-4">${metric("Max risk / trade",pct(config.max_risk_per_trade_pct,1),money(p.equity*config.max_risk_per_trade_pct))}${metric("Daily loss",pct(Math.max(0,-p.daily_pnl/p.day_start_equity)),`Limit ${pct(config.max_daily_loss_pct,1)}`)}${metric("Drawdown",pct(p.drawdown_pct),`Limit ${pct(config.max_account_drawdown_pct,1)}`)}${metric("Portfolio risk",pct(p.portfolio_risk_pct),`Limit ${pct(config.max_portfolio_risk_pct,1)}`)}</div><div class="grid grid-2 mt"><div class="card"><h3 class="section-title">Limit utilization</h3>${riskBar("Daily loss",Math.max(0,-p.daily_pnl/p.day_start_equity),config.max_daily_loss_pct)}${riskBar("Drawdown",p.drawdown_pct,config.max_account_drawdown_pct)}${riskBar("Portfolio risk",p.portfolio_risk_pct,config.max_portfolio_risk_pct)}${riskBar("Gross exposure",p.gross_exposure_pct,config.max_gross_exposure_pct)}</div><div class="card"><h3 class="section-title">Configured simulation policy</h3>${jsonBlock(config)}</div></div><div class="card mt"><h3 class="section-title">Open-position risk</h3>${table(p.open_positions.map(x=>({...x,unit_risk:Math.abs(x.entry_price-x.stop_loss),open_risk:Math.abs(x.entry_price-x.stop_loss)*x.quantity,unrealized:(x.mark_price-x.entry_price)*x.quantity*(x.side==="LONG"?1:-1)})),[{key:"symbol",label:"Instrument"},{key:"side",label:"Side"},{key:"quantity",label:"Quantity"},{key:"unit_risk",label:"Unit risk",render:r=>price(r.unit_risk)},{key:"open_risk",label:"Open risk",render:r=>money(r.open_risk)},{key:"unrealized",label:"Unrealized",render:r=>signed(r.unrealized)}],"No open-position risk")}</div>`;}catch(error){content.innerHTML+=`<div class="alert error">${esc(error.message)}</div>`;}}

function backtestForm(){return `<div class="card mb"><form id="backtest-form"><div class="form-grid"><div class="field"><label>Instrument</label><input name="ticker" value="EUR_USD"></div><div class="field"><label>Timeframe</label><select name="timeframe"><option>5m</option><option>15m</option><option>1h</option><option selected>1d</option></select></div><div class="field"><label>Bars</label><input name="rows" type="number" value="300" min="60" max="1000"></div><div class="field"><label>Fast / slow EMA</label><div class="row"><input name="fast_ema" type="number" value="9"><input name="slow_ema" type="number" value="15"></div></div><div class="field"><label>Risk / trade %</label><input name="risk" type="number" step="0.1" value="1"></div><div class="field"><label>ATR stop / target</label><div class="row"><input name="stop" type="number" step="0.1" value="1.5"><input name="target" type="number" step="0.1" value="3"></div></div><div class="field"><label>Fees / slippage bps</label><div class="row"><input name="fees" type="number" step="0.1" value="1"><input name="slippage" type="number" step="0.1" value="2"></div></div><div class="field"><label>&nbsp;</label><button class="button primary" type="submit">Run historical backtest ↗</button></div></div></form></div>`;}
async function renderBacktesting(){content.innerHTML=head("Backtesting laboratory","Chronological OANDA practice-history simulation with costs and buy-and-hold context")+backtestForm()+`<div id="backtest-results">${state.backtest?backtestResults(state.backtest):`<div class="empty">Configure and run a backtest to inspect its equity curve and trade history.</div>`}</div>`;$("#backtest-form").onsubmit=runBacktest;}
async function runBacktest(event){event.preventDefault();const f=new FormData(event.target),button=event.target.querySelector("button");button.disabled=true;$("#backtest-results").innerHTML=loading("Running chronological event simulation…");try{const body={ticker:f.get("ticker"),timeframe:f.get("timeframe"),rows:Number(f.get("rows")),config:{fast_ema:Number(f.get("fast_ema")),slow_ema:Number(f.get("slow_ema")),risk_per_trade_pct:Number(f.get("risk"))/100,atr_stop_multiple:Number(f.get("stop")),atr_target_multiple:Number(f.get("target")),fee_bps:Number(f.get("fees")),slippage_bps:Number(f.get("slippage"))}};state.backtest=await api("/api/v1/backtests",{method:"POST",body:JSON.stringify(body)});$("#backtest-results").innerHTML=backtestResults(state.backtest);}catch(error){$("#backtest-results").innerHTML=`<div class="alert error">${esc(error.message)}</div>`;}finally{button.disabled=false;}}
function backtestResults(r){const m=r.metrics,c=r.equity_curve;return provenance("HISTORICAL SIMULATION",r.methodology,"python")+`<div class="grid grid-5">${metric("Total return",num(m.total_return_pct,2)+"%",`Buy & hold ${num(r.buy_and_hold_return_pct,2)}%`,pnlClass(m.total_return_pct))}${metric("Max drawdown",num(m.max_drawdown_pct,2)+"%")}${metric("Sharpe / Sortino",`${num(m.sharpe_ratio)} / ${num(m.sortino_ratio)}`)}${metric("Win rate",pct(m.win_rate,1),`${m.trade_count} closed trades`)}${metric("Expectancy",money(m.expectancy),`Profit factor ${m.profit_factor===null?"∞ / undefined":num(m.profit_factor)}`)}</div><div class="card mt"><h3 class="section-title">Strategy vs buy-and-hold</h3>${lineChart(c.map(x=>x.timestamp),[{name:"Strategy equity",values:c.map(x=>x.equity),color:"#60a5fa",area:true},{name:"Buy & hold",values:c.map(x=>x.buy_and_hold),color:"#94a3b8",dash:true}])}</div><div class="card mt"><h3 class="section-title">Drawdown curve</h3>${lineChart(c.map(x=>x.timestamp),[{name:"Drawdown %",values:c.map(x=>x.drawdown*100),color:"#fb7185",area:true}],{percent:true,height:240})}</div><div class="card mt"><h3 class="section-title">Trade-by-trade history</h3>${table(r.trades,[{key:"entry_timestamp",label:"Entry time",render:x=>dateFmt(x.entry_timestamp)},{key:"side",label:"Side"},{key:"entry_price",label:"Entry",render:x=>price(x.entry_price)},{key:"exit_price",label:"Exit",render:x=>price(x.exit_price)},{key:"quantity",label:"Qty",render:x=>num(x.quantity,2)},{key:"pnl",label:"Net P&L",render:x=>signed(x.pnl)},{key:"exit_reason",label:"Exit"},{key:"fees",label:"Fees",render:x=>money(x.fees)}],"No completed trades under these rules")}</div>`;}

async function renderMonitoring(){content.innerHTML=head("Agent monitoring","Execution traces, latency, tools, token usage, errors, and disagreements")+loading();try{const runs=await api("/api/v1/research/runs?limit=100");content.innerHTML=head("Agent monitoring","Execution traces, latency, tools, token usage, errors, and disagreements")+provenance("EXECUTION EVIDENCE","Traces are recorded during actual agent execution and persisted with each research run.","python")+`<div class="card"><div class="field"><label>Research run</label><select id="run-select"><option value="">Select a run to inspect</option>${runs.map(r=>`<option value="${r.run_id}">${r.ticker} · ${r.timeframe} · ${r.outcome} · ${dateFmt(r.created_at)}</option>`).join("")}</select></div></div><div id="monitor-results" class="mt">${runTable(runs)}</div>`;$("#run-select").onchange=event=>inspectRun(event.target.value,true);if(state.inspect){const id=state.inspect;state.inspect=null;$("#run-select").value=id;inspectRun(id,true);}}catch(error){content.innerHTML+=`<div class="alert error">${esc(error.message)}</div>`;}}
async function inspectRun(id,embedded=false){if(!id)return;if(!embedded){state.inspect=id;navigate("monitoring");return;}const target=$("#monitor-results");target.innerHTML=loading("Loading persisted report and traces…");try{const[r,traces]=await Promise.all([api(`/api/v1/research/runs/${id}`),api(`/api/v1/research/traces?run_id=${id}`)]);target.innerHTML=`<div class="card"><div class="split"><h3 class="section-title">${r.proposal?.symbol||r.data_sources?.primary?.symbol||"Research"} decision</h3>${badge(r.outcome)}</div><ul class="reason-list">${r.reasons.map(x=>`<li>${esc(x)}</li>`).join("")}</ul></div><div class="card mt"><h3 class="section-title">Agent execution traces</h3>${traceHTML(traces)}</div><div class="grid grid-2 mt"><div class="card"><h3 class="section-title">Disagreements & missing information</h3>${jsonBlock({disagreements:r.supervisor?.disagreements||[],concerns:r.supervisor?.concerns||[],missing:r.supervisor?.missing_information||[]})}</div><div class="card"><h3 class="section-title">Complete report</h3>${jsonBlock(r)}</div></div>`;}catch(error){target.innerHTML=`<div class="alert error">${esc(error.message)}</div>`;}}
window.inspectRun=inspectRun;window.prepareAssistant=prepareAssistant;

$$('.nav-item').forEach(button=>button.onclick=()=>navigate(button.dataset.page));
$("#menu-button").onclick=()=>$("#sidebar").classList.toggle("open");
loadIntegrations();loadQuote();navigate("overview");
setInterval(()=>loadQuote(),15000);
